#!/usr/bin/python3

import subprocess,json,os

def run_command(command):
    result = os.popen(command).read()
    return (result)

def writeline(oid,line):
    f.write(oid + ":" + line + "\n")

def singlelinetooid(oid,title,line):
    writeline(oid, title)
    line = line.lstrip().rstrip()
    writeline(oid + ".0", line)

def multilinetooid(oid,title,multistr):
    writeline(oid, title)
    linenumber = 0
    for line in multistr.splitlines():
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        writeline(oid + "." + str(linenumber), line)
    writeline(oid + ".0", str(linenumber))

base_oid = ""
f = open("/tmp/snmpdata.txt", "w")

#IPMITOOL
if os.path.isfile("/dev/ipmi0") or os.path.isfile("/dev/ipmi/0") or os.path.isfile("/dev/ipmidev/0"):
    for i in range(1,5):
        match i:
            case 1:
                command = """/usr/bin/ipmitool sensor | sed -e "s/ *| */;/g" """
                title = "ipmitool sensor"
                data = run_command(command)
            case 2:
                command = "/usr/bin/ipmitool sensor -v"
                title = "ipmitool sensor verbose"
                data = run_command(command)
            case 3:
                command = """ /usr/bin/ipmitool sdr list | sed -e "s/ *| */;/g" """
                title = "ipmitool sdr"
                data = run_command(command)
            case 4:
                command = "/usr/bin/ipmitool sdr list -v"
                title = "ipmitool sdr verbose"
                data = run_command(command)
        multilinetooid(base_oid + ".4." + str(i), title, data)

# RAID
if os.path.isfile("/usr/local/sbin/arcconf"):
    # get temperatures
    command = """ /usr/local/sbin/arcconf GETCONFIG 1 PD | /usr/bin/grep "Current Temperature" | /usr/bin/awk '{ print $4 }' """
    data = run_command(command)
    linenumber = 0
    for line in data.splitlines():
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        singlelinetooid(base_oid + ".3.1."+str(linenumber), "temperature disk " + str(linenumber), line)

    command = """ /usr/local/sbin/arcconf GETCONFIG 1  | grep "S.M.A.R.T. warnings" | awk '{ print $4 }' """
    data = run_command(command)
    linenumber = 0
    for line in data.splitlines():
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        singlelinetooid(base_oid + ".3.2."+str(linenumber), "SMART Warnings disk " + str(linenumber), line)

# OTHER MONOLINE VALUES
for i in range(1,4):
    match i:
        case 1:
            command = """ /usr/sbin/smartctl -H /dev/sda | /usr/bin/grep "SMART overall-health self-assessment test result: " | sed "s/SMART overall-health self-assessment test result: //" """
            title = "smartctl /dev/sda"
            data = run_command(command)
        case 2:
            command = """ /usr/sbin/smartctl -H /dev/sdb | /usr/bin/grep "SMART overall-health self-assessment test result: " | sed "s/SMART overall-health self-assessment test result: //" """
            title = "smartctl /dev/sdb"
            data = run_command(command)
        case 3:
            command = """
passed=$(/usr/sbin/smartctl --scan | /usr/bin/grep -E "^/dev/(sd|nvme)" | /usr/bin/awk '{ print $1 }' | while read i; do /usr/sbin/smartctl -H $i | /usr/bin/grep "SMART overall-health self-assessment test result: " | /usr/bin/grep -v "SMART overall-health self-assessment test result: PASSED"; done | /usr/bin/wc -l)
if [ $passed -ne 0 ]; then
  echo DISKPROBLEM
else
  echo DISKOK
fi
"""
            title = "disk status"
            data = run_command(command)
    singlelinetooid(base_oid + ".2." + str(i), title, data)

# OTHER MULTILINES VALUES
for i in range(1,11):
    match i:
        case 1:
            command = "/usr/sbin/crm status"
            title = command
            data = run_command(command)
        case 2:
            command = "/usr/bin/virsh --connect qemu:///system domstats"
            title = "virsh domstats"
            data = run_command(command)
        case 3:
            command = """
/usr/bin/virsh --connect qemu:///system list --name | sed -s "/^$/d" | while read i
do
  echo Domain: \'$i\'
  /usr/bin/virsh --connect qemu:///system dommemstat --domain $i
done
"""
            title = "virsh dommemstat"
            data = run_command(command)
        case 4:
            command = "/usr/bin/ceph status"
            title = "ceph status"
            data = run_command(command)
        case 5:
            command = "/usr/local/bin/virt-df.sh"
            title = "virt-df"
            data = run_command(command)
        case 6:
            command = "/usr/bin/virsh -c qemu:///system list --all"
            title = "virsh list"
            data = run_command(command)
        case 7:
            command = "/usr/bin/ceph status --format=json | /usr/bin/jq -c .pgmap"
            title = "ceph usage"
            data = run_command(command)
        case 8:
            command = """
/usr/sbin/smartctl --scan | /usr/bin/awk '{ print $1 }' | while read i; do
  temp=$(/usr/sbin/smartctl -a $i | /usr/bin/grep Temperature_Celsius | /usr/bin/awk '{ print $10 }')
  if [ ! -z "$temp" ]
  then
    echo "$i;$temp"
  fi
done
"""
            title = "temperature disks"
            data = run_command(command)
        case 9:
            command = """
/usr/sbin/smartctl --scan | /usr/bin/grep -E "^/dev/(sd|nvme)" | /usr/bin/awk '{ print $1 }' | while read i; do
  echo $i
  j=$(echo $i | sed "s/\/dev\///")
  k=$(/usr/bin/udevadm info -q symlink --path=/sys/block/$j | tr " " "\n" | sort | /usr/bin/grep 'disk/by-path' | head -n 1 | /usr/bin/awk '{print "/dev/" $1}')
  echo $k
  /usr/sbin/smartctl --attributes -H $i | sed '0,/^=== START OF READ SMART DATA SECTION ===$/d'
  echo ------------------------------------------
done
"""
            title = "smartctl"
            data = run_command(command)
        case 10:
            command = "/usr/sbin/lvs -a -o +devices,lv_health_status"
            title = "lvs status"
            data = run_command(command)

    multilinetooid(base_oid + ".1." + str(i), title, data)

f.close()
