#!/usr/bin/python3
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import subprocess,json,os,stat
import xmltodict
from xml.parsers.expat import ParserCreate, ExpatError, errors

def run_command(command):
    result = subprocess.check_output(command, shell=True, executable='/bin/bash').decode()
    return (result)

def writeline(oid,line):
    f.write(oid + ":" + line + "\n")

def singlelinetooid(oid,title,line):
#    writeline(oid, title)
    line = line.lstrip().rstrip()
    writeline(oid + ".0", line)

def multilinetooid(oid,title,multistr):
#    writeline(oid, title)
    linenumber = 0
    for line in multistr.splitlines():
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        writeline(oid + "." + str(linenumber), line)
    writeline(oid + ".0", str(linenumber))

def dictarrayoid(oid,title,a):
#    writeline(oid, title)
    keys = list(a[0].keys())
    for key in keys:
        writeline(oid + ".0." + str(keys.index(key)), key)
    for d in a[1:]:
        for k in range(0,len(d)):
            writeline(oid + "." + str(a.index(d)) + "." + str(k), d[keys[k]])

base_oid = ""
f = open("/tmp/snmpdata.txt", "w")

grep = "/usr/bin/grep"
sort = "/usr/bin/sort"
awk = "/usr/bin/awk"
sed = "/usr/bin/sed"
tr = "/usr/bin/tr"
head = "/usr/bin/head"
echo = "/usr/bin/echo"
jq = "/usr/bin/jq"
cut = "/usr/bin/cut"

# .1 --> "other" multiline values
# .2 --> "other" monoline values
# .3 --> raid/arcconf values
# .4 --> ipmitool values
# .5 --> global "disk need to be replaced" values

# Disk needs to be replaced logic
# We assume the server may have up to 4 disks, and while running this script we will keep in mind if any check is a hint the disk needs to be replaces (with the RAID tests, then the SMART tests and then the LVM tests).
# We start with a "no pb" status and toggle to "not ok" if needed
globalreplacedisk = "OK" # we store a global status, including a problem detected on LVM for example
replacedisk = ["OK","OK","OK","OK"] # we store a status per disk

#IPMITOOL
ipmitool = "/usr/bin/ipmitool"
def exist_and_is_character(filepath):
    try:
        r = stat.S_ISCHR(os.lstat(filepath)[stat.ST_MODE])
    except FileNotFoundError:
        return False
    return r

if exist_and_is_character("/dev/ipmi0") or exist_and_is_character("/dev/ipmi/0") or exist_and_is_character("/dev/ipmidev/0"):
    for i in range(1,5):
        match i:
            case 1:
                command = f""" {ipmitool} sensor | {sed} -e "s/ *| */;/g" """
                title = "ipmitool sensor"
                data = run_command(command)
            case 2:
                command = f""" {ipmitool} sensor -v """
                title = "ipmitool sensor verbose"
                data = run_command(command)
            case 3:
                command = f""" {ipmitool} sdr list | {sed} -e "s/ *| */;/g" """
                title = "ipmitool sdr"
                data = run_command(command)
            case 4:
                command = f""" {ipmitool} sdr list -v"""
                title = "ipmitool sdr verbose"
                data = run_command(command)
        multilinetooid(base_oid + ".4." + str(i), title, data)

# RAID
arcconf = "/usr/local/sbin/arcconf"
if os.path.isfile(arcconf):
    # get temperatures
    command = f""" {arcconf} GETCONFIG 1 PD | {grep} "Current Temperature" | {awk} '{{ print $4 }}' """
    data = run_command(command)
    linenumber = 0
    for line in data.splitlines():
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        singlelinetooid(base_oid + ".3.1."+str(linenumber), "temperature disk " + str(linenumber), line)

    command = f""" {arcconf} GETCONFIG 1  | {grep} "S.M.A.R.T. warnings" | {awk} '{{ print $4 }}' """
    data = run_command(command)
    linenumber = 0
    for line in data.splitlines():
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        singlelinetooid(base_oid + ".3.2."+str(linenumber), "SMART Warnings disk " + str(linenumber), line)
        if line != "0":
            replacedisk[linenumber-1] = "RAID SMART Warnings on disk"+str(linenumber)
            globalreplacedisk = "RAID SMART Warnings on one disk"

    command = f""" {arcconf} GETCONFIG 1  | {grep} "S.M.A.R.T. warnings" | {awk} '{{sum += $4}} END {{print sum}}' """
    title = "ARCCONF sum of SMART WARNINGS"
    data = run_command(command)
    data = data.lstrip().rstrip()
    singlelinetooid(base_oid + ".3.3", title, data)
    if data != "0" and data != "":
        globalreplacedisk = "RAID SMART Warnings on one disk"

    command = f""" {arcconf} GETCONFIG 1 AR | {grep} -E "Device [0-9]" | {cut} -d":" -f2 | {awk} '{{ print $1 }}' """
    data = run_command(command)
    linenumber = 0
    for line in data.splitlines():
        title = f"RAID array device {linenumber} status"
        linenumber = linenumber + 1
        line = line.lstrip().rstrip()
        singlelinetooid(base_oid + ".3.4."+str(linenumber), title, line)
        if line != "Present":
            replacedisk[linenumber-1] = 1

    for i in range(0,4):
        command = f""" {arcconf} GETCONFIG 1 PD 0 {i} | {grep} "S.M.A.R.T. warnings" | {awk} '{{ print $4 }}' """
        title = f"ARCCONF SMART WARNINGS device {i+1}"
        data = run_command(command)
        data = data.lstrip().rstrip()
        if data != "0" and data!="":
            replacedisk[i] = 1
        singlelinetooid(base_oid + ".3.5."+str(i+1)+".1", title, data)


# OTHER MONOLINE VALUES
# .2.[1-4] --> smart self assessement for /dev/sd[a-d]
# .2.5 -->lvs full status
# .2.5.0 --> column name
# .2.5.1 --> first LV data
# .2.5.2 --> second LV data, etc

# >.2.6 --> other monolines

i = 0
for disk in ["sda","sdb","sdc","sdd"]:
    command = f""" /usr/sbin/smartctl -H /dev/{disk} | {grep} "SMART overall-health self-assessment test result: " | {sed} "s/SMART overall-health self-assessment test result: //" """
    title = f"""smartctl /dev/{disk}"""
    data = run_command(command)
    data = data.lstrip().rstrip()
    if data != "PASSED" and data != "":
        replacedisk[i] = 1
    i = i + 1
    singlelinetooid(base_oid + ".2." + str(i), title, data)

command = f""" /usr/sbin/lvs -a -o +devices,lv_health_status --reportformat json | {jq} -c .report[].lv """
title = "lvs full status json"
data = run_command(command)
data = json.loads(data)
dictarrayoid(base_oid + ".2.5", title, data)

for i in range(6,11):
    match i:
        case 6:
            command = f"""
/usr/sbin/smartctl --scan | {grep} -E "^/dev/(sd|nvme)" | {awk} '{{ print $1 }}' | while read i; do /usr/sbin/smartctl -H $i | {grep} "SMART overall-health self-assessment test result: " | {grep} -v "SMART overall-health self-assessment test result: PASSED"; done | /usr/bin/wc -l """
            title = "disk smartctl status"
            data = run_command(command)
            data = data.lstrip().rstrip()
            if data == "0":
                data = "SMARTOK"
            else:
                data = "SMARTPROBLEM"
                globalreplacedisk = "SMART tests not passed"
        case 7:
            command = f""" /usr/sbin/lvs -a -o +devices,lv_health_status --reportformat json | {jq} -c . """
            title = "lvs full status json"
            data = run_command(command)
        case 8:
            command = f""" /usr/sbin/lvs -o name,lv_health_status --reportformat json | {jq} -c . """
            title = "lvs basic status json"
            data = run_command(command)
        case 9:
            command = f""" /usr/sbin/lvs -o name,lv_health_status --reportformat json | {jq} -c '.report[].lv[] | select( .lv_health_status != "" )' """
            title = "lvs sumup status"
            data = run_command(command)
            if data == "":
                data = "NO LVS PROBLEM"
            else:
                data = "LVS PROBLEM: " + data
                globalreplacedisk = "LVS health not OK"
        case 10:
            command = f""" ceph status --format json-pretty | {jq} -c -r .health.status """
            title = "ceph health status"
            data = run_command(command)
    singlelinetooid(base_oid + ".2." + str(i), title, data)

# OTHER MULTILINES VALUES
for i in range(1,12):
    match i:
        case 1:
            command = f""" /usr/sbin/crm status"""
            title = command
            data = run_command(command)
        case 2:
            command = f"""
FILE=/tmp/domstats.txt
if [ -f $FILE ]
then
  OLDTIME=120
  CURTIME=$(date +%s)
  FILETIME=$(stat $FILE -c %Y)
  TIMEDIFF=$(expr $CURTIME - $FILETIME)
  if [ $TIMEDIFF -gt $OLDTIME ]; then
    /usr/bin/virsh --connect qemu:///system domstats > $FILE
  fi
else
  /usr/bin/virsh --connect qemu:///system domstats > $FILE
fi
cat $FILE
"""
            title = "virsh domstats"
            data = run_command(command)
        case 3:
            command = f"""
FILE=/tmp/dommemstat.txt
function create_or_rewrite {{
  /usr/bin/virsh --connect qemu:///system list --name | sed -s "/^$/d" | while read i
  do
    echo Domain: \'$i\'
    /usr/bin/virsh --connect qemu:///system dommemstat --domain $i
  done > $FILE
}}
if [ -f $FILE ]
then
  OLDTIME=120
  CURTIME=$(date +%s)
  FILETIME=$(stat $FILE -c %Y)
  TIMEDIFF=$(expr $CURTIME - $FILETIME)

  if [ $TIMEDIFF -gt $OLDTIME ]; then
    create_or_rewrite
  fi
else
  create_or_rewrite
fi
cat $FILE
"""
            title = "virsh dommemstat"
            data = run_command(command)
        case 4:
            command = f""" /usr/bin/ceph status """
            title = "ceph status"
            data = run_command(command)
        case 5:
            command = f"""
FILE=/tmp/virt-df.txt
if [ -f $FILE ]
then
  OLDTIME=3600
  CURTIME=$(date +%s)
  FILETIME=$(stat $FILE -c %Y)
  TIMEDIFF=$(expr $CURTIME - $FILETIME)
  if [ $TIMEDIFF -gt $OLDTIME ]; then
    /usr/local/bin/virt-df.sh > $FILE
  fi
else
  /usr/local/bin/virt-df.sh > $FILE
fi
cat $FILE
"""
            title = "virt-df"
            data = run_command(command)
        case 6:
            command = f""" /usr/bin/virsh -c qemu:///system list --all """
            title = "virsh list"
            data = run_command(command)
        case 7:
            command = f""" /usr/bin/ceph status --format=json | {jq} -c .pgmap """
            title = "ceph usage"
            data = run_command(command)
        case 8:
            command = f"""
/usr/sbin/smartctl --scan | {awk} '{{ print $1 }}' | while read i; do
  temp=$(/usr/sbin/smartctl -a $i | {grep} Temperature_Celsius | {awk} '{{ print $10 }}')
  if [ ! -z "$temp" ]
  then
    {echo} "$i;$temp"
  fi
done
"""
            title = "temperature disks"
            data = run_command(command)
        case 9:
            command = f"""
/usr/sbin/smartctl --scan | {grep} -E "^/dev/(sd|nvme)" | {awk} '{{ print $1 }}' | while read i; do
  {echo} $i
  j=$({echo} $i | {sed} "s/\/dev\///")
  k=$(/usr/bin/udevadm info -q symlink --path=/sys/block/$j | {tr} " " "\n" | {sort} | {grep} 'disk/by-path' | {head} -n 1 | {awk} '{{ print "/dev/" $1 }}')
  {echo} $k
  /usr/sbin/smartctl --attributes -H $i | {sed} '0,/^=== START OF READ SMART DATA SECTION ===$/d'
  {echo} ------------------------------------------
done
"""
            title = "smartctl"
            data = run_command(command)
        case 10:
            command = f""" /usr/sbin/lvs -a -o +devices,lv_health_status """
            title = "lvs status"
            data = run_command(command)
        case 11:
            command = f""" /usr/sbin/crm status --as-xml """
            title = "crm status json"
            xml_status = run_command(command)
            try:
                dict_status = xmltodict.parse(xml_status, attr_prefix='')
                data = json.dumps(dict_status)
                data1 = json.dumps(dict_status["crm_mon"]["summary"])
                multilinetooid(base_oid + ".1.11.0.1", title + " summary", data1)
                data2 = json.dumps(dict_status["crm_mon"]["nodes"])
                multilinetooid(base_oid + ".1.11.0.2", title + " nodes", data2)
                continue
            except ExpatError:
                pass

    multilinetooid(base_oid + ".1." + str(i), title, data)

if 1 in replacedisk:
    globalreplacedisk = "Problem on one disk"
for i in range(1,5):
    singlelinetooid(base_oid + ".5." + str(i), "replace disk " + str(i), replacedisk[i-1])
singlelinetooid(base_oid + ".5.5", "replace disk global",globalreplacedisk)

f.close()
