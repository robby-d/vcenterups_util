# vcenterups_util

Triggers a VMware vCenter deployment shutdown (i.e. of the vcenter server vm and all vms it manages) if a Tripplite or Cyberpower UPS gets below a certain percentage battery remaining.

## Requirements

* A Tripplite UPS with a SNMPWEBCARD device, or a Cyberpower UPS with an RMCARD remote access module
* UPS assigned an IP address and SNMP v1 enabled via the web GUI
* VMware vCenter host managing 1 or more ESXi systems (tested with vCenter 7)

## Installation

These instructions are written for Ubuntu 22.04 LTS.

Install some base dependencies:

```
    sudo apt-get install -y python3-pip python3-venv
    sudo apt-get install -y libsnmp-dev snmp-mibs-downloader
```

Create the virtual environment:

```
    sudo mkdir /opt/vcenterups_util
    sudo chown ${USER}:{GROUP} /opt/vcenterups_util
    git clone https://github.com/robby-dermody/vcenterups_util.git /opt/vcenterups_util
    python3 -m venv /opt/vcenterups_util/env
    /opt/vcenterups_util/env/bin/pip3 install -U easysnmp pyyaml requests
```

### Create a role, user and mapping in vCenter

In vCenter, under Administration -> Roles, create a new user role called `vcenterups Users` and give it the following permissions:
```
Virtual Machine -> Power off
Virtual Machine -> Power on
```

Then under Administration -> Users and Groups, create a new user named `vcenterups_user` and assign it a secure password.

Finally, under Administration -> Global Permissions, add a mapping entry for `vcenterups_user` to assign it the `vcenterups Users` role. Make sure `Propagate to children` is checked.


### Copy the config file

Copy the `conf/vcenterups_util.yaml.orig` configuration file template to `conf/vcenterups_util.yaml` and modify as necessary. Multiple deployment sections can be added to support multiple vcenter system/UPS combinations.

Once done copying and editing this file, properly set its permissions:
```
chmod 600 conf/vcenterups_util.yaml
```

### Allow shutdown command access from non-root user
The program needs to be able to shutdown the system from the command line without running as root. To allow this, run the following command as the user you intend to run the program as:

```
sudo bash -c "echo '${USER} ALL = (root) NOPASSWD: /usr/sbin/shutdown' > /etc/sudoers.d/vcenterups_util"
```

### DRY RUN TEST

Edit `vcenterups_util.yaml` and set `initiate_shutdown_at_batt_pct_remaining`  to `100` temporarily to get the program to trigger when run. Test the script by running `~/vcenterups_util/env/bin/python3 ~/vcenterups_util/vcenterups_util.py --debug --dry-run`. You should see it run and print out the ESXi server information to screen. `CTRL-C` to terminate the program and then modify the `initiate_shutdown_at_batt_pct_remaining` value back to the desired value.

### POWER DOWN TEST

Unplug the UPS and run `tail -f logs/vcenterups_util.log`. You should see the script run every minute. When the percent battery remaining reaches the value you set for `initiate_shutdown_at_batt_pct_remaining` in your config, you should see it command your ESXi server to shutdown all VMs and shut itself down.

