#!/bin/bash

/usr/sbin/smartctl --scan | grep -E "^/dev/(sd|nvme)" | awk '{ print $1 }' | while read i; do
  echo ------------------------------------------
  echo $i
  echo ------------------------------------------
  /usr/sbin/smartctl -a $i
  echo ------------------------------------------
done
