#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

local_tmp_dir=$1
remote_shell=$2
remote_dir=$3
fulldatedir=$4
guest=$5
incdate=$6

[ -z "$local_tmp_dir" ] && { echo "var local_tmp_dir empty"; exit 1; }
[ -z "$remote_shell" ] && { echo "var remote_shell empty"; exit 2; }
[ -z "$remote_dir" ] && { echo "var remote_dir empty"; exit 3; }
[ -z "$fulldatedir" ] && { echo "var fulldatedir empty"; exit 4; }
[ -z "$guest" ] && { echo "var guest empty"; exit 5; }
[ -z "$incdate" ] && { echo "var incdate empty"; exit 6; }

f="$local_tmp_dir""$d"
mkdir -p $f

#called with : ./restore_vm.sh /data2/tmp "ssh -p 22" cephbackup@ip:/mnt/nasopf/seapath/backups_ceph_cluster_lot1/ backup_ceph_202203110733 VM1 202203110836
#local_tmp_dir=/data2/tmp
#remote_dir=cephbackup@ip:/mnt/nasopf/seapath/backups_ceph_cluster/
#fulldatedir=backup_ceph_202203110733
#guest=VM2
#incdate=202203110836

echo $local_tmp_dir
echo $remote_shell
echo $remote_dir
echo $fulldatedir
echo $guest
echo $incdate

fulldate=`echo $fulldatedir | sed -e "s/backup_ceph_//"`

echo Removing tmp local dir
echo rm -rf "$local_tmp_dir"/*, press enter to proceed
read
rm -rf "$local_tmp_dir"/*
echo
echo copying files locally
echo rsync -ave "$remote_shell" --progress $remote_dir$fulldatedir/*_"$guest"-* $local_tmp_dir/
rsync -ave "$remote_shell" --progress $remote_dir$fulldatedir/*_"$guest"-* $local_tmp_dir/
echo rsync -ave "$remote_shell" --progress $remote_dir$fulldatedir/*_"$guest"_* $local_tmp_dir/
rsync -ave "$remote_shell" --progress $remote_dir$fulldatedir/*_"$guest"_* $local_tmp_dir/
echo
echo creating vm xml with no disk
echo python3 /usr/local/bin/remove_disk_xml.py $local_tmp_dir/system_"$guest"-"$incdate".xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml
python3 /usr/local/bin/remove_disk_xml.py $local_tmp_dir/system_"$guest"-"$incdate".xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml
echo
echo creating base vm
echo vm-mgr create -n $guest --force --disable --xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml -i $local_tmp_dir/system_"$guest"_"$fulldate".qcow2
vm-mgr create -n $guest --force --disable --xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml -i $local_tmp_dir/system_"$guest"_"$fulldate".qcow2
echo
echo creating base snapshot
echo rbd snap create system_"$guest"@$fulldate
rbd snap create system_"$guest"@$fulldate
echo
for difffile in `ls $local_tmp_dir/*.diff`
do
  datediff=`echo $difffile | sed -e s/.*_// -e s/\.diff//`
  if [ $datediff -le $incdate ]; then
    echo $difffile
    echo rbd import-diff $difffile rbd/system_"$guest"
    rbd import-diff $difffile rbd/system_"$guest"
  fi
done
echo
echo Restoring metadata
for metafile in $(ls $local_tmp_dir/system_${guest}-meta-*-${incdate}.txt)
do
  key=$(echo $metafile | sed -e s/.*system_${guest}-meta-// -e s/-${incdate}.txt//)
  echo "metadata name = " $key
  echo rbd image-meta set system_${guest} $key "$(cat $metafile)"
  rbd image-meta set system_${guest} $key "$(cat $metafile)"
done
echo
echo Starting VM
echo vm-mgr enable -n $guest
vm-mgr enable -n $guest
exit
