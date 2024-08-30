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

echo "Include VM : $include_vm"
echo "Exclude VM : $exclude_vm"
echo "------------------------------------"
L_VM=$( rbd list | grep -E "($include_vm)"  | grep -E -v "($exclude_vm)" | sed -e "s/system_//g" )
echo "List of Guests to backup: " $L_VM
echo "------------------------------------"
echo Removing old full backups local dirs
echo rm -rf "$local_dir"*, press enter to proceed
read
rm -rf "$local_dir"*

d=`date +%Y%m%d%H%M`
f="$local_dir""$d"
mkdir -p $f
#rbd list | while read i
CMD="rbd list"
LIST_VM=$( $CMD | grep -E "($include_vm)"  | grep -E -v "($exclude_vm)" )
for i in $LIST_VM
do
  echo $i
  echo sparsifying
  rbd sparsify $i
  echo purging snapshots
  rbd snap purge rbd/$i
  echo creating base snapshot
  rbd snap create rbd/$i@$d
  echo backuping vm xml
  rbd image-meta get rbd/$i xml > $f/$i-$d.xml
  echo backuping metadata all
  rbd image-meta list rbd/$i > $f/$i-metaall-$d.txt
  echo backuping metadata one by one
  guest=$(echo $i | sed s/^system_//)
  for j in `python3 /usr/local/bin/get_metadata.py $guest`
  do
    echo "   " $j
    rbd image-meta get rbd/$i $j > $f/$i-meta-$j-$d.txt
  done
  echo backuping snapshot
  qemu-img convert -f raw -O qcow2 rbd:rbd/$i@$d $f/$i"_"$d.qcow2
  echo ----
done
rsync -ave "$remote_shell" --progress $f $remote_dir
