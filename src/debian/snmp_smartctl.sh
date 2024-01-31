#!/bin/bash

/usr/sbin/smartctl --scan | grep -E "^/dev/(sd|nvme)" | awk '{ print $1 }' | while read i; do
  echo $i
  j=$(echo $i | sed "s/\/dev\///")
  k=$(/usr/bin/udevadm info -q symlink --path=/sys/block/$j | tr " " "\n" | sort | grep 'disk/by-path' | head -n 1 | awk '{print "/dev/" $1}')
  echo $k
  smartctl --attributes -H $i | sed '0,/^=== START OF READ SMART DATA SECTION ===$/d'
  echo ------------------------------------------
done
