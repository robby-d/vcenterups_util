# cpesxi_util

Simple script to trigger an VMware vCenter deployment shutdown (i.e. of the vcenter server vm and all vms it manages) if a Tripplite or Cyberpower UPS gets below a certain percentage battery remaining.

## Requirements

* A Tripplite UPS with a SNMPWEBCARD device, or a Cyberpower UPS with an RMCARD remote access module
* UPS assigned an IP address and SNMP v1 enabled via the web GUI
* VMware vCenter host managing 1 or more ESXi systems (tested with vCenter 7)

## Installation

The below instructions are written for Ubuntu 18.04 LTS.

### Check out the project

Check out `cpesxi_util` to your home directory (or anywhere else you see fit)

```
cd
git clone git@github.com:robby-dermody/cpesxi_util.git
```

### Install `cpesxi_util`  dependencies

```
sudo apt-get install git python3 python3-pip
sudo apt-get install libsnmp-dev snmp-mibs-downloader
sudo pip3 install easysnmp
```

### Create a role, user and mapping in vCenter

In vCenter, under Administration -> Roles, create a new user role called `cpesxi Users` and give it the following permissions:
```
Virtual Machine -> Power off
Virtual Machine -> Power on
```

Then under Administration -> Users and Groups, create a new user named `cpesxi_user` and assign it a secure password.

Finally, under Administration -> Global Permissions, add a mapping entry for `cpesxi_user` to assign it the `cpesxi Users` role. Make sure `Propagate to children` is checked.


### Copy the config file

Copy `~/cpesxi_util/cpesxi_util.yaml.orig` configuration file template to `~/cpesxi_util/cpesxi_util.yaml` and modify as necessary. It is structured as follows:

```
deployment_NAME:
  vcenter_host: vcenter server IP/hostname
  vcenter_username: vcenter server admin user username
  vcenter_password: vcenter user password
  vcenter_vm_name: The VM name of the vcenter server (e.g. vcenter, vcenter01, etc)
  executing_host_vm_name: If this script is running on a VM managed by this vcenter platform, put the name of that VM here
  ups_type: "tripplite" or "cyberpower"
  ups_host: UPS IP/hostname
  ups_snmpv1_community: SNMP community (normally "public")
  initiate_shutdown_at_batt_pct_remaining: when the % UPS battery remaining gets to or under this level, the script will shutdown the vcenter deployment
```

Multiple deployment sections can be added to support multiple vcenter system/UPS combinations.

Once done creating this file, properly set its permissions:
```
chmod 600 cpesxi_util.yaml
```

### Allow shutdown command access from non-root user
The script needs to be able to shutdown the system from the command line without running as root. To allow this, run the following command, replacing `MY_USER` with the user you intend to run the script as:

```
sudo bash -c "echo 'MY_USER ALL = (root) NOPASSWD: /usr/sbin/shutdown' > /etc/sudoers.d/cpesxi_util"
```

### DRY RUN TEST

Edit `cpesxi_util.yaml` and set `initiate_shutdown_at_batt_pct_remaining`  to `100` temporarily to get the script to trigger when run. Test the script by running `~/cpesxi_util/cpesxi_util.py --debug --dry-run`. You should see it run and print out the ESXi server information to screen. Modify the `initiate_shutdown_at_batt_pct_remaining` value back to the desired value.

### Set up cronjob

Create a cronjob via `crontab -e` and insert the following text to run the script every minute:
`* * * * * ~/cpesxi_util/cpesxi_util.py --debug 2>/dev/null`

### POWER DOWN TEST

Unplug the UPS and run `tail -f ~/cpesxi_util/logs/cpesxi_util.log`. You should see the script run every minute. When the percent battery remaining reaches the value you set for `initiate_shutdown_at_batt_pct_remaining` in your config, you should see it command your ESXi server to shutdown all VMs and shut itself down.

