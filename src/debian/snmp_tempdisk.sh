#!/usr/bin/env bash

/usr/sbin/smartctl --scan | awk '{ print $1 }' | while read i; do
  temp=$(/usr/sbin/smartctl -a $i | grep Temperature_Celsius | awk '{ print $10 }')
  if [ ! -z "$temp" ]
  then
    echo "$i;$temp"
  fi
done
