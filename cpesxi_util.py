#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
shutdown ESXi if the 
'''

import os
import sys
import re
import time
import argparse
import datetime
import logging
import logging.handlers
import time
import yaml
import json
import subprocess
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

from easysnmp import Session

PROG_NAME = "cpesxi_util"
ESXI_SHUTDOWN_MIN_REPEAT_PERIOD = 3600 # 1 hour

logger = None

def get_vc_session(vc_hostname, username, password):
    '''get the vCenter server session'''
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
    s = requests.Session()
    s.verify = False   # disable checking server certificate
    s.auth = (username, password) # basic auth
    try:
        r = s.post("https://{}/api/session".format(vc_hostname))
    except requests.exceptions.ConnectionError:
        logger.error("Error connecting to vCenter {}".format(vc_hostname))
        return False
    if r.status_code != 201:
        logger.error("Get vCenter session failed. Status code: {}, error: {}".format(r.status_code, r.text))
        return False
    logger.debug("Got vCenter session ID {}".format(r.headers['vmware-api-session-id']))
    s.headers.update({'vmware-api-session-id': r.headers['vmware-api-session-id']})
    return s

def get_vm_list(s, vc_hostname):
    '''Function to get all the VMs from vCenter inventory'''   
    r = s.get("https://" + vc_hostname + "/api/vcenter/vm")
    if r.status_code != 200:
        logger.error("List VMs failed. Status code: {}, error: {}".format(r.status_code, r.text))
        return False
    return json.loads(r.text)

def get_vm_poweredon_list(s, vc_hostname):
    '''Function to get all the VMs from vCenter inventory that are powered on'''
    vm_query_params = {"power_states": ["POWERED_ON"]}
    r = s.get("https://" + vc_hostname + "/api/vcenter/vm", params = vm_query_params)
    if r.status_code != 200:
        logger.error("Power on VM failed. Status code: {}, error: {}".format(r.status_code, r.text))
        return False
    return json.loads(r.text)

def guest_shutdown(s, vmid, vc_hostname):
    '''Shut down guest VM'''
    vm_action = {"action": "shutdown"}
    r = s.post("https://" + vc_hostname + "/api/vcenter/vm/" + vmid + "/guest/power", params = vm_action)
    if r.status_code != 200:
        logger.error("Power off VM failed. Status code: {}, error: {}".format(r.status_code, r.text))
        return False
    return r

def get_program_dir():
    return os.path.realpath(os.path.dirname(__file__))

def set_up_logging(debug):
    LOG_MAX_SIZE = 1024 * 1024 * 2  # 2MB
    LOG_FORMAT = '%(asctime)s %(name)s %(levelname)s: %(message)s'
    LOG_NUM_ROTATIONS = 5

    log_filename = "{}.log".format(PROG_NAME)
    logger = logging.getLogger()
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO, format=LOG_FORMAT)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("easysnmp.interface").setLevel(logging.WARNING)
    # Add the log message handler to the logger
    logfile_handler = logging.handlers.RotatingFileHandler(
        os.path.join(get_program_dir(), "logs", log_filename), maxBytes=LOG_MAX_SIZE, backupCount=LOG_NUM_ROTATIONS)
    logfile_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(logfile_handler)
    return logger

def load_config():
    with open(os.path.join(get_program_dir(), "{}.yaml".format(PROG_NAME)), 'r') as ymlfile:
        config = yaml.safe_load(ymlfile)
    for section in config:
        if not section.startswith('deployment_'):
            logger.error("Invalid config section {}".format(section))
            return False
        #required fields
        for p in ('vcenter_host', 'vcenter_username', 'vcenter_password', 'vcenter_vm_name',
                  'ups_type', 'ups_host', 'ups_snmpv1_community', 'initiate_shutdown_at_batt_pct_remaining'):
            if p not in config[section] or not config[section][p]:
                logger.error("Missing or empty property '{}'".format(p))
                return False
        if 'executing_host_vm_name' not in config[section]:
            config[section]['executing_host_vm_name'] = ''
        
        assert config[section]['ups_type'] in ('tripplite', 'cyberpower')
    return config

def get_ups_stats(deployment_config):
    # Triplite OIDs, from: https://assets.tripplite.com/flyer/supported-snmp-oids-technical-application-bulletin-en.pdf
    TRIPPLITE_OID_BATTERY_TIME_LEFT_MIN = ".1.3.6.1.2.1.33.1.2.3.0"  # UPSEstimatedMinutesRemaining
    TRIPPLITE_OID_BATTERY_CAPACITY_LEFT_PCT = ".1.3.6.1.2.1.33.1.2.4.0"  # UPSEstimatedChargeRemaining
    TRIPPLITE_OID_CURRENT_INPUT_VOLTAGE = ".1.3.6.1.2.1.33.1.3.3.1.3.1"  # UPSInputVoltage
    #Cyberpower UPS OIDs, from: https://www.reddit.com/r/homelab/comments/5pdxwb/cyberpower_ups_and_grafana_now_with_snmp/
    CYBERPOWER_OID_BATTERY_TIME_LEFT_TICKS = ".1.3.6.1.4.1.3808.1.1.1.2.2.4.0"
    CYBERPOWER_OID_BATTERY_CAPACITY_LEFT_PCT = ".1.3.6.1.4.1.3808.1.1.1.2.2.1.0"
    CYBERPOWER_OID_CURRENT_INPUT_VOLTAGE = ".1.3.6.1.4.1.3808.1.1.1.3.2.1.0"

    # read state from UPS
    stats = {}
    logger.debug("Reading power state from {} UPS @ {} (SNMP: {})".format(
        deployment_config['ups_type'], deployment_config['ups_host'], deployment_config['ups_snmpv1_community']))
    snmp_session = Session(hostname=deployment_config['ups_host'], community=deployment_config['ups_snmpv1_community'], version=1)

    if deployment_config['ups_type'] == 'tripplite':        
        stats['ups_input_voltage'] = int(snmp_session.get(TRIPPLITE_OID_CURRENT_INPUT_VOLTAGE).value)
        stats['ups_is_discharging'] = not bool(stats['ups_input_voltage'])  # voltage is 0 when unit is discharging
        stats['ups_min_left'] = int(snmp_session.get(TRIPPLITE_OID_BATTERY_TIME_LEFT_MIN).value)
        stats['ups_pct_left'] = float(snmp_session.get(TRIPPLITE_OID_BATTERY_CAPACITY_LEFT_PCT).value)
    else:
        assert deployment_config['ups_type'] == 'cyberpower'
        stats['ups_input_voltage'] = int(snmp_session.get(CYBERPOWER_OID_CURRENT_INPUT_VOLTAGE).value)
        stats['ups_is_discharging'] = not bool(stats['ups_input_voltage'])  # voltage is 0 when unit is discharging
        stats['ups_min_left'] = int(snmp_session.get(CYBERPOWER_OID_BATTERY_TIME_LEFT_TICKS).value) / 6000.0
        stats['ups_pct_left'] = float(snmp_session.get(CYBERPOWER_OID_BATTERY_CAPACITY_LEFT_PCT).value)
    return stats

def do_vcenter_shutdown(deployment_config, is_dry_run):
    MAX_SHUTDOWN_WAIT_COUNT = 10
    SECONDS_BETWEEN_SHUTDOWN_AND_CHECK = 15
    #VCENTER_SHUTDOWN_WAIT_TIME_SECONDS = 100

    #Get vCenter server session
    s = get_vc_session(deployment_config['vcenter_host'], deployment_config['vcenter_username'], deployment_config['vcenter_password'])
    if s is False:
        return False

    # Get list of VMs powered on
    vm_list = get_vm_poweredon_list(s, deployment_config['vcenter_host'])
    if vm_list is False:
        return False

    logger.info("Seeing {} VMs".format(len(vm_list)))
    logger.debug("Full VM list: {}".format(vm_list))

    filtered_vm_list = [vm for vm in vm_list if vm["name"] not in (deployment_config['vcenter_vm_name'], deployment_config['executing_host_vm_name'])]
    vcenter_vm_list = [vm for vm in vm_list if vm["name"] == deployment_config['vcenter_vm_name']]

    assert len(vcenter_vm_list) in (0, 1)
    if len(vcenter_vm_list) == 0:
        logger.error("Cannot find vcenter server named {}".format(deployment_config['vcenter_vm_name']))
    
    # Reorder the list with the vcenter server last, leaving out the vm host executing this script (if there is one), which will be shutdown via shell command
    vm_list_to_shutdown = filtered_vm_list + vcenter_vm_list  # leave out executing vm host
    logger.info("Shutting down the following VMs: {}".format(', '.join([vm['name'] for vm in vm_list_to_shutdown])))

    # shut down non-vcenter vms first
    for vm in filtered_vm_list:
        logger.info("Shutting down {} ({}) (dry run: {})...".format(vm["name"], vm["vm"], is_dry_run))
        if not is_dry_run:
            guest_shutdown(s, vm["vm"], deployment_config['vcenter_host'])  # todo: handle API call error?

    if not is_dry_run:
        for i in range(MAX_SHUTDOWN_WAIT_COUNT):
            logger.info("Waiting {} seconds before checking VM powered on status (try {} of {})...".format(
                SECONDS_BETWEEN_SHUTDOWN_AND_CHECK, i + 1, MAX_SHUTDOWN_WAIT_COUNT))
            time.sleep(SECONDS_BETWEEN_SHUTDOWN_AND_CHECK)
            # See if any VMs still powered on (excluding vcenter and executing_host_vm_name, if any)
            vms_powered_on = get_vm_poweredon_list(s, deployment_config['vcenter_host'])
            if vms_powered_on is False:
                return False
            #remove vcenter and executing_host_vm_name from the result
            vms_powered_on = [vm for vm in vms_powered_on if vm['name'] not in (deployment_config['vcenter_vm_name'], deployment_config['executing_host_vm_name'])]
            if len(vms_powered_on):
                logger.info("Still waiting on {} VMs to shut down: {}".format(len(filtered_vm_list), ','.join([vm['name'] for vm in filtered_vm_list])))
            else: # all done with VM shutdown
                break
        else:
            logger.error("Did not finish VM shutdowns in the allowed time, aborting.")
            return False

    # now shut down vcenter
    logger.info("Shutting down vcenter server {} (dry run: {})...".format(vcenter_vm_list[0]['name'], is_dry_run))
    if not is_dry_run:
        guest_shutdown(s, vcenter_vm_list[0]['vm'], deployment_config['vcenter_host'])    
        #time.sleep(VCENTER_SHUTDOWN_WAIT_TIME_SECONDS) # wait a certain amount of time before assuming vcenter is shut down

    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action='store_true', default=False, help="increase output verbosity")
    parser.add_argument("--dry-run", action='store_true', default=False, help="dry run only (don't trigger shutdown)")
    args = parser.parse_args()
    
    global logger
    logger = set_up_logging(args.debug)
    config = load_config()
    if config == False:
        logger.error("Could not load config")
        sys.exit(1)

    # load state
    state_file_path = os.path.join(get_program_dir(), "{}.state".format(PROG_NAME))
    if os.path.exists(state_file_path):
        with open(state_file_path, 'r') as f:
            state = json.load(f)
    else:
        state = {}

    # for each UPS-vcenter deployment combo...
    for deployment in config:
        logger.info("Processing {}".format(deployment))
        state.setdefault(deployment, {'success': None})
        state[deployment].setdefault('shutdown-times', [])
            
        ups_stats = get_ups_stats(config[deployment])

        logger.info("UPS capacity has {}% remaining (> {}% allowed) ({} minutes runtime left, UPS {} discharging)".format(
                ups_stats['ups_pct_left'], config[deployment]['initiate_shutdown_at_batt_pct_remaining'], ups_stats['ups_min_left'],
                "IS" if ups_stats['ups_is_discharging'] else "IS NOT"))

        now_epoch = int(time.time())

        # skip making a shutdown request if we have recently made one
        if len(state[deployment]['shutdown-times']):
            last_shutdown = state[deployment]['shutdown-times'][-1]
            assert last_shutdown < now_epoch
            if not args.dry_run and now_epoch - last_shutdown < ESXI_SHUTDOWN_MIN_REPEAT_PERIOD:
                logger.info("Skipping shutdown request as the last one was made {} seconds ago".format(now_epoch - last_shutdown))
                continue

        # only allow shutdown if UPS is actively discharging
        if not args.dry_run and not ups_stats['ups_is_discharging']:
            logger.info("Not making shutdown request: On AC power")
            continue

        # check if we need to make a shutdown request
        if ups_stats['ups_pct_left'] > config[deployment]['initiate_shutdown_at_batt_pct_remaining']:
            logger.info("Not making shutdown request: On battery power, but levels are still above {}%".format(
                config[deployment]['initiate_shutdown_at_batt_pct_remaining']))
            continue

        logger.info("SHUTDOWN {}INITIATED - UPS has {}% left is < {}% allowed".format(
            'DRY RUN ' if args.dry_run else '', ups_stats['ups_pct_left'], config[deployment]['initiate_shutdown_at_batt_pct_remaining']))

        state[deployment]['shutdown-times'].append(now_epoch)  # log this time as a shutdown

        # shut down the vcenter environment
        state[deployment]['success'] = do_vcenter_shutdown(config[deployment], args.dry_run)

        # if this script is running on a VM in this vcenter deployment that is shutting down,
        # we will need to shut down this system via shell command, as vcenter is already down (or shutting down)
        if state[deployment]['success'] and config[deployment]['executing_host_vm_name']:
            logger.info("Shutting down this system ({}) via shell command, in 1 minute (dry run: {})...".format(config[deployment]['executing_host_vm_name'], args.dry_run))
            if not args.dry_run:
                cmd = "sudo shutdown -P +1"  # schedule shutdown for 1 minute out
                child = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=os.environ.copy())
                stdout_and_stderr = child.communicate()[0].decode("utf-8")  # wait for call to finish
                rc = child.returncode
                if rc != 0:
                    logger.info("Invalid response from shutdown: {}".format(stdout_and_stderr))
                    state[deployment]['success']  = False
    
    with open(state_file_path, 'w') as f:
        json.dump(state, f)

    return all([deployment['success'] in (True, None) for deployment in state.values()])
    


if __name__ == "__main__":
    sys.exit(0 if main() == True else 1)
