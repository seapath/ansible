#!/bin/bash
for devname in /dev/rbd*
do
  /usr/bin/rbd unmap $devname 2>/dev/null
done
for guest in `virsh --connect qemu:///system list --all | /usr/bin/awk 'NR>2 { print $2 }' | sed /^$/d`
do
  mkdir -p /t
  /usr/bin/umount /t 2>/dev/null
  /usr/sbin/lvs > /tmp/lvs1
  devname=`/usr/bin/rbd map --read-only system_"$guest"`
  /usr/sbin/lvs 2>/dev/null > /tmp/lvs2
  sort < /tmp/lvs1 | /usr/bin/awk '{ print $1 " " $2 " " $4 }' > /tmp/lvs1.sorted
  sort < /tmp/lvs2 | /usr/bin/awk '{ print $1 " " $2 " " $4 }' > /tmp/lvs2.sorted
  declare -A lvsdiff
  while IFS="," read -r a b; do
    b=$(echo $b | sed 's/ *$//g')
    lvsdiff["$a"]="$b"
  done < <(comm -13 /tmp/lvs1.sorted /tmp/lvs2.sorted | /usr/bin/awk '{ print $1 "," $2 }')
  rm -f /tmp/lvs1 /tmp/lvs2 /tmp/lvs1.sorted /tmp/lvs2.sorted
  for lvname in "${!lvsdiff[@]}"
  do
    vgname=${lvsdiff[$lvname]}
    #echo "lvname is '$lvname'  => vgname is '$vgname'"
    /usr/sbin/lvchange -ay /dev/$vgname/$lvname
    /usr/bin/mount -o ro,noload /dev/$vgname/$lvname /t 2>/dev/null
    returncode=$?
    if [ $returncode -eq 0 ]; then
      /usr/bin/df -k | grep -E "\/t$" | /usr/bin/awk -v guest="$guest" '{ print guest ":" $1 " total:" $2 " used:" $3 " available:" $4 " disk-usage:" $5 }'
    fi
    /usr/bin/umount /t 2>/dev/null
    /usr/sbin/lvchange -an /dev/$vgname/$lvname
  done
  unset lvsdiff
  for part in $devname"p"*
  do
    /usr/bin/mount -o ro,noload $part /t 2>/dev/null
    returncode=$?
    if [ $returncode -eq 0 ]; then
      /usr/bin/df -k | grep -E "\/t$" | /usr/bin/awk -v guest="$guest" '{ print guest ":" $1 " total:" $2 " used:" $3 " available:" $4 " disk-usage:" $5 }'
    fi
    /usr/bin/umount /t 2>/dev/null
  done
  /usr/bin/rbd unmap $devname
done
