# cpesxi_util

Simple script to trigger an ESXi server shutdown if a Cyberpower UPS registers a low battery state. Created due to lack of ESXi 6.7 support with Cyberpower PowerPanel Business Edition for Virtual Machines.

## Requirements

* A Cyberpower UPS with an RMCARD remote access module
* RMCARD assigned an IP address and SNMP v1 enabled via the web GUI
* ESXi server (tested with ESXi 6.7)

## Installation

The below instructions are written for Ubuntu 18.04 LTS.

### Check out the project

Check out `cpesxi_util` to your home directory (or anywhere else you see fit)

```
cd
git clone git@github.com:robby-dermody/cpesxi_util.git
```

### Install vSphere CLI tools

Download vSphere Linux x86_64 CLI utilities from [here](https://my.vmware.com/web/vmware/details?downloadGroup=VS-CLI-670&productId=742).

Then:
```
tar -zxvf VMware-vSphere-CLI-*.x86_64.tar.gz
sudo apt install -y build-essential perl-doc libmodule-build-perl libssl-dev libxml-libxml-perl libsoap-lite-perl libuuid-perl libcrypt-ssleay-perl libarchive-zip-perl libsocket6-perl libio-socket-inet6-perl libnet-inet6glue-perl
sudo ./vmware-vsphere-cli-distrib/vmware-install.pl
```

Then, to fix a perl dependency issue, do the following:
```
sudo cpan
install GAAS/libwww-perl-5.837.tar.gz
exit
```

### Install other `cpesxi_util`  dependencies
```
sudo apt-get install git python3 python3-pip
sudo apt-get install libsnmp-dev snmp-mibs-downloader
sudo pip3 install easysnmp
```

### (Optional) Create a new admin user on your ESXi server 

### Copy the config file

Copy `~/cpesxi_util/cpesxi_util.yaml.orig` configuration file template to `~/cpesxi_util/cpesxi_util.yaml` and modify as necessary. It is structured as follows:

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

### DRY RUN TEST

Edit `cpesxi_util.yaml` and set `initiate_shutdown_at_batt_pct_remaining`  to `100` temporarily to get the script to trigger when run. Test the script by running `~/cpesxi_util/cpesxi_util.py --debug --dry-run`. You should see it run and print out the ESXi server information to screen. Modify the `initiate_shutdown_at_batt_pct_remaining` value back to the desired value.

### Set up cronjob

Create a cronjob via `crontab -e` and insert the following text to run the script every minute:

`* * * * * ~/cpesxi_util/cpesxi_util.py --debug`

### POWER DOWN TEST

Unplug the UPS and run `tail -f ~/cpesxi_util/logs/cpesxi_util.log`. You should see the script run every minute. When the percent battery remaining reaches the value you set for `initiate_shutdown_at_batt_pct_remaining` in your config, you should see it command your ESXi server to shutdown all VMs and shut itself down.

