#!/bin/bash
# Copyright (C) 2024, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

# This script allows the host to know the available disk space of guests, so that it can expose it with snmp

process_unit () {
  unitname=$1
  lvbool=$2
  if [ $lvbool -eq 1 ]; then
    /usr/sbin/lvchange -ay /dev/$vgname/$lvname
  fi
  blkidstr=$(/usr/sbin/blkid $unitname)
  if [[ $blkidstr == *" TYPE="* ]]
  then
    fstype=$(/usr/sbin/blkid $unitname | /usr/bin/sed -e "s/^.* TYPE=\"//" -e "s/\".*$//")
  else
    return
  fi
  if [ "$fstype" != "swap" -a "$fstype" != "LVM2_member" -a "$fstype" != "partition" ]
  then
    if [ "$fstype" == "ext4" ];then
      /usr/bin/mount -o ro,noload $unitname /t
    elif [ "$fstype" == "xfs" ]; then
      /usr/bin/mount -o ro,norecovery $unitname /t
    elif [ "$fstype" == "ufs" ]; then
      /usr/bin/mount -o ro,ufstype=ufs2 -t ufs $unitname /t
    else
      /usr/bin/mount -o ro $unitname /t
    fi
  else
    if [ $lvbool -eq 1 ]; then
      /usr/sbin/lvchange -an $unitname
    fi
    return
  fi
  returncode=$?
  if [ $returncode -eq 0 ]; then
    /usr/bin/df -k /t | /usr/bin/grep -E "\/t$" | /usr/bin/awk -v guest="$guest" '{ print guest ":" $1 " total:" $2 " used:" $3 " available:" $4 " disk-usage:" $5 }'
  fi
  /usr/bin/umount /t 2>/dev/null
  if [ $lvbool -eq 1 ]; then
    /usr/sbin/lvchange -an $unitname
  fi
}

/usr/sbin/pvs -o pv_name,vg_uuid | /usr/bin/grep /dev/rbd | awk '{ print $2 }' | while read vg_uuid; do
  /usr/sbin/vgchange -an --select vg_uuid=$vg_uuid
done
for devname in /dev/rbd*
do
  /usr/bin/rbd unmap $devname 2>/dev/null
done
for guest in `virsh --connect qemu:///system list --all | /usr/bin/awk 'NR>2 { print $2 }' | /usr/bin/sed /^$/d`
do
  mkdir -p /t
  /usr/bin/umount /t 2>/dev/null
  /usr/sbin/lvs > /tmp/lvs1
  devname=`/usr/bin/rbd map --read-only system_"$guest"`
  /usr/sbin/lvs 2>/dev/null > /tmp/lvs2
  /usr/bin/sort < /tmp/lvs1 | /usr/bin/awk '{ print $1 " " $2 " " $4 }' > /tmp/lvs1.sorted
  /usr/bin/sort < /tmp/lvs2 | /usr/bin/awk '{ print $1 " " $2 " " $4 }' > /tmp/lvs2.sorted
  declare -A lvsdiff
  while IFS="," read -r a b; do
    b=$(/usr/bin/echo $b | /usr/bin/sed 's/ *$//g')
    lvsdiff["$a"]="$b"
  done < <(comm -13 /tmp/lvs1.sorted /tmp/lvs2.sorted | /usr/bin/awk '{ print $1 "," $2 }')
  /usr/bin/rm -f /tmp/lvs1 /tmp/lvs2 /tmp/lvs1.sorted /tmp/lvs2.sorted
  for lvname in "${!lvsdiff[@]}"
  do
    vgname=${lvsdiff[$lvname]}
    process_unit /dev/$vgname/$lvname 1
  done
  unset lvsdiff
  for part in $devname"p"*
  do
    process_unit $part 0
  done
  /usr/bin/rbd unmap $devname
done
