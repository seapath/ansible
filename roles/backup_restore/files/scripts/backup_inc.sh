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

#local_dir="/data2/backup_ceph_"
#remote_shell="ssh -p 22"
#remote_dir="cephbackup@ip:/mnt/nasopf/seapath/backups_ceph_cluster_proj/"

d=`date +%Y%m%d%H%M`
latest_full=`ls -d "$local_dir"* | tail -n 1`
[ ! -d "$latest_full" ] && { echo "latest full backup not found"; exit 3; }

echo "Include VM : $include_vm"
echo "Exclude VM : $exclude_vm"
echo "------------------------------------"
L_VM=$( rbd list | grep -E "($include_vm)"  | grep -E -v "($exclude_vm)" | sed -e "s/system_//g" )
echo "List of Guests to backup: " $L_VM
echo "------------------------------------"
echo "press enter to proceed"
read

#rbd list | while read i
CMD="rbd list"
LIST_VM=$( $CMD | grep -E "($include_vm)"  | grep -E -v "($exclude_vm)" )
for i in $LIST_VM
do
  echo $i
  latest=`rbd snap list rbd/$i | tail -n 1 | awk '{ print $2 }'`
  echo creating new snapshot
  rbd snap create rbd/$i@$d
  echo creating diff
  rbd export-diff --from-snap $latest rbd/$i@$d $latest_full/"$i"_"$latest"_"$d".diff
  echo backuping vm xml
  rbd image-meta get rbd/$i xml > $latest_full/$i-$d.xml
  echo backuping metadata all
  rbd image-meta list rbd/$i > $latest_full/$i-metaall-$d.txt
  echo backuping metadata one by one
  guest=$(echo $i | sed s/^system_//)
  for j in `python3 /usr/local/bin/get_metadata.py $guest`
  do
    echo "   " $j
    rbd image-meta get rbd/$i $j > $latest_full/$i-meta-$j-$d.txt
  done
done
rsync -ave "$remote_shell" --progress $latest_full $remote_dir
