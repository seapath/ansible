#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

local_dir=$1
remote_shell=$2
remote_dir=$3
include_vm=$4
exclude_vm=$5

[ -z "$local_dir" ] && { echo "var local_dir empty"; exit 1; }
[ -z "$remote_shell" ] && { echo "var remote_shell empty"; exit 2; }
[ -z "$remote_dir" ] && { echo "var remote_dir empty"; exit 3; }

# Guests are identified by their system disk (system_<guest>). Their
# additional disks (data_<guest>_<n>) are backed up along with them.
LIST_GUESTS=$( rbd list | grep -E "^system_" | sed -e "s/^system_//" | grep -E "($include_vm)" | grep -E -v "($exclude_vm)" )

echo "Include VM : $include_vm"
echo "Exclude VM : $exclude_vm"
echo "------------------------------------"
echo "List of Guests to backup: " $LIST_GUESTS
echo "------------------------------------"
echo Removing old full backups local dirs
echo rm -rf "$local_dir"*, press enter to proceed
read
rm -rf "$local_dir"*

d=`date +%Y%m%d%H%M`
f="$local_dir""$d"
mkdir -p $f
for guest in $LIST_GUESTS
do
  images="system_$guest $(rbd list | grep -E "^data_${guest}_[0-9]+$")"
  for i in $images
  do
    echo $i
    echo sparsifying
    rbd sparsify $i
    echo purging snapshots
    rbd snap purge rbd/$i
    echo creating base snapshot
    rbd snap create rbd/$i@$d
    echo backuping snapshot
    qemu-img convert -f raw -O qcow2 rbd:rbd/$i@$d $f/$i"_"$d.qcow2
  done
  i=system_$guest
  echo backuping vm xml
  rbd image-meta get rbd/$i xml > $f/$i-$d.xml
  echo backuping metadata all
  rbd image-meta list rbd/$i > $f/$i-metaall-$d.txt
  echo backuping metadata one by one
  for j in `python3 /usr/local/bin/get_metadata.py $guest`
  do
    echo "   " $j
    rbd image-meta get rbd/$i $j > $f/$i-meta-$j-$d.txt
  done
  echo ----
done
rsync -ave "$remote_shell" --progress $f $remote_dir
