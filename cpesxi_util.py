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

from easysnmp import Session

PROG_NAME = "cpesxi_util"
ESXI_SHUTDOWN_MIN_REPEAT_PERIOD = 3600 # 1 hour

#https://www.reddit.com/r/homelab/comments/5pdxwb/cyberpower_ups_and_grafana_now_with_snmp/
CYBERPOWER_OID_BATTERY_TIME_LEFT_TICKS = "1.3.6.1.4.1.3808.1.1.1.2.2.4.0"
CYBERPOWER_OID_BATTERY_CAPACITY_LEFT_PCT = "1.3.6.1.4.1.3808.1.1.1.2.2.1.0"

logger = None

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
        config = yaml.load(ymlfile)
    for section in config:
        if not section.startswith('deployment_'):
            logger.error("Invalid config section {}".format(section))
            return False
        for p in ('esxi_host', 'esxi_username', 'esxi_password', 'ups_host', 'ups_snmpv1_community', 'initiate_shutdown_at_batt_pct_remaining'):
            if p not in config[section] or not config[section][p]:
                logger.error("Missing or empty property '{}'".format(p))
                return False
    return config

def main():
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

    # for each UPS-ESXi combo
    for deployment in config:
        logger.info("Processing {}".format(deployment))
        state.setdefault(deployment, {})
        state[deployment].setdefault('shutdown-times', [])
            
        # read power state from UPS
        logger.debug("Reading power state from UPS @ {} (SNMP: {})".format(
            config[deployment]['ups_host'], config[deployment]['ups_snmpv1_community']))
        session = Session(hostname=config[deployment]['ups_host'], community=config[deployment]['ups_snmpv1_community'], version=1)
        ups_ticks_left = session.get('.' + CYBERPOWER_OID_BATTERY_TIME_LEFT_TICKS)
        ups_min_left = int(ups_ticks_left.value) / 6000.0
        ups_pct_left = float(session.get('.' + CYBERPOWER_OID_BATTERY_CAPACITY_LEFT_PCT).value)

        logger.info("UPS capacity has {}% remaining (> {}% allowed) ({} minutes runtime left)".format(
                ups_pct_left, config[deployment]['initiate_shutdown_at_batt_pct_remaining'], ups_min_left))

        now_epoch = int(time.time())

        # skip making a shutdown request if we have recently made one
        if len(state[deployment]['shutdown-times']):
            last_shutdown = state[deployment]['shutdown-times'][-1]
            assert last_shutdown < now_epoch
            if now_epoch - last_shutdown < ESXI_SHUTDOWN_MIN_REPEAT_PERIOD:
                logger.info("Skipping shutdown request, as the last one was made {} seconds ago".format(now_epoch - last_shutdown))
                continue

        # TODO: only allow shutdown if UPS is on battery power

        # check if we need to make a shutdown request
        if ups_pct_left > config[deployment]['initiate_shutdown_at_batt_pct_remaining']:
            logger.info("Not making shutdown request")
            continue

        logger.info("SHUTDOWN {}INITIATED - UPS has {}% left is < {}% allowed".format(
            'DRY RUN ' if args.dry_run else '', ups_pct_left, config[deployment]['initiate_shutdown_at_batt_pct_remaining']))

        if args.dry_run:
            subcommand = "--operation info"
        else:  # for real
            subcommand = "--operation shutdown --force"
        
        env = os.environ.copy()
        env['VI_PASSWORD'] = config[deployment]['esxi_password']
        cmd = "vicfg-hostops --server {} --username {} {}".format(config[deployment]['esxi_host'], config[deployment]['esxi_username'], subcommand)

        child = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        stdout_and_stderr = child.communicate()[0].decode("utf-8")  # wait for call to finish
        rc = child.returncode
        if rc != 0:
            logger.info("Invalid response from vicfg-hostops: {}".format(stdout_and_stderr))
        else:
            logger.debug("SUCCESS - vicfg-hostops returned: {}".format(stdout_and_stderr))

        # log this time as a shutdown
        state[deployment]['shutdown-times'].append(now_epoch)
    
    with open(state_file_path, 'w') as f:
        json.dump(state, f)


if __name__ == "__main__":
    main()
