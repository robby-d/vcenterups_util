# cpesxi_util

Simple script to trigger an ESXi server shutdown if a Cyberpower UPS registers a low battery state. Created due to lack of ESXi support with Cyberpower PowerPanel Business Edition for Virtual Machines.

## Requirements

* A Cyberpower UPS with an RMCARD remote access module
* RMCARD assigned an IP address and SNMP v1 enabled via the web GUI
* ESXi server (tested with ESXi 6.7)

## Installation

The below instructions are written for Ubuntu 18.04 LTS.

* Install vSphere Command line tools

* Install script dependencies:
```
sudo apt-get install python3 python3-pip
sudo pip3 install easysnmp
```

* (Optional) Create a new admin user on your ESXi server 

* Check out `cpesxi_util` to your home directory (or anywhere else you see fit):
```
cd
git clone git@github.com:robby-dermody/cpesxi_util.git
```

* Copy the `~/cpesxi_util/cpesxi_util.yaml.orig` configuration file template to `~/cpesxi_util/cpesxi_util.yaml` and modify as necessary. It is structured as follows:
```
deployment_NAME:
  esxi_host: ESXI server IP/hostname
  esxi_username: ESXI server admin user username
  esxi_password: ESXI user password
  ups_host: UPS RMCARD IP/hostname
  ups_snmpv1_community: SNMP community (normally "public")
  initiate_shutdown_at_batt_pct_remaining: when the % UPS battery remaining gets to or under this level, the script will shutdown the ESXi server
```

Multiple deployment sections can be added to support multiple ESXi server/UPS combinations.

* **DRY RUN TEST**: Edit `cpesxi_util.yaml` and set `initiate_shutdown_at_batt_pct_remaining`  to `100` temporarily to get the script to trigger when run. Test the script by running `~/cpesxi_util/cpesxi_util.py --debug --dry-run`. You should see it run and print out the ESXi server information to screen. Modify the `initiate_shutdown_at_batt_pct_remaining` value back to the desired value.

* Create a cronjob via `crontab -e` and insert the following text to run the script every minute:
`* * * * * ~/cpesxi_util/cpesxi_util.py --debug`

* **POWER DOWN TEST**: Unplug the UPS and run `tail -f ~/cpesxi_util/logs/cpesxi_util.log`. You should see the script run every minute. When the percent battery remaining reaches the value you set for `initiate_shutdown_at_batt_pct_remaining` in your config, you should see it command your ESXi server to shutdown all VMs and shut itself down.

