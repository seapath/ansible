#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

set -u

local_dir=${1:-}
remote_shell=${2:-}
remote_dir=${3:-}
include_vm=${4:-}
exclude_vm=${5:-}

[ -z "$local_dir" ] && { echo "var local_dir empty"; exit 1; }
[ -z "$remote_shell" ] && { echo "var remote_shell empty"; exit 2; }
[ -z "$remote_dir" ] && { echo "var remote_dir empty"; exit 3; }

d=$(date +%Y%m%d%H%M)
latest_full=$(ls -d "$local_dir"* | tail -n 1)
[ ! -d "$latest_full" ] && { echo "latest full backup not found"; exit 3; }

# Guests are identified by their system disk (system_<guest>). Their
# additional disks (data_<guest>_<n>) are backed up along with them.
LIST_GUESTS=$( rbd list | grep -E "^system_" | sed -e "s/^system_//" | grep -E "($include_vm)" | grep -E -v "($exclude_vm)" )

echo "Include VM : $include_vm"
echo "Exclude VM : $exclude_vm"
echo "------------------------------------"
echo "List of Guests to backup: " $LIST_GUESTS
echo "------------------------------------"
echo "press enter to proceed"
read -r

not_in_full=""
for guest in $LIST_GUESTS
do
  images="system_$guest $(rbd list | grep -E "^data_${guest}_[0-9]+$")"
  for i in $images
  do
    echo "$i"
    latest=$(rbd snap list "rbd/$i" | tail -n 1 | awk '{ print $2 }')
    if [ -z "$latest" ]; then
      echo "WARNING: rbd/$i has no snapshot: it is not part of the latest full backup and cannot be backed up incrementally"
      not_in_full="$not_in_full $i"
      continue
    fi
    echo creating new snapshot
    rbd snap create "rbd/$i@$d"
    echo creating diff
    rbd export-diff --from-snap "$latest" "rbd/$i@$d" "$latest_full/${i}_${latest}_${d}.diff"
  done
  i=system_$guest
  echo backuping vm xml
  rbd image-meta get "rbd/$i" xml > "$latest_full/$i-$d.xml"
  echo backuping metadata all
  rbd image-meta list "rbd/$i" > "$latest_full/$i-metaall-$d.txt"
  echo backuping metadata one by one
  for j in $(python3 /usr/local/bin/get_metadata.py "$guest")
  do
    echo "    $j"
    rbd image-meta get "rbd/$i" "$j" > "$latest_full/$i-meta-$j-$d.txt"
  done
done
if [ -n "$not_in_full" ]; then
  echo "------------------------------------"
  echo "WARNING: the following disks are missing from the latest full backup"
  echo "and were NOT backed up:$not_in_full"
  echo "Run a new full backup to include them."
  echo "------------------------------------"
fi
rsync -ave "$remote_shell" --progress "$latest_full" "$remote_dir"
