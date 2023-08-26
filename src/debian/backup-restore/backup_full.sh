#!/bin/bash

local_dir=$1
remote_shell=$2
remote_dir=$3

[ -z "$local_dir" ] && { echo "var local_dir empty"; exit 1; }
[ -z "$remote_shell" ] && { echo "var remote_shell empty"; exit 2; }
[ -z "$remote_dir" ] && { echo "var remote_dir empty"; exit 3; }

echo Removing old full backups local dirs
echo rm -rf "$local_dir"*, press enter to proceed
read
rm -rf "$local_dir"*

d=`date +%Y%m%d%H%M`
f="$local_dir""$d"
mkdir -p $f
rbd list | while read i
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
