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
# Additional disks (data_<guest>_<n>) are restored from their full backup
# qcow2, in index order so vm-mgr recreates them under their original names
data_images=$(cd $local_tmp_dir && ls data_"$guest"_*_"$fulldate".qcow2 2>/dev/null | sed -e "s/_$fulldate\.qcow2$//" | sort -t_ -k3 -n)
additional_disk_args=()
for img in $data_images
do
  additional_disk_args+=(--additional-disk "$local_tmp_dir/${img}_${fulldate}.qcow2")
done
echo creating base vm
echo vm-mgr create -n $guest --force --disable --xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml -i $local_tmp_dir/system_"$guest"_"$fulldate".qcow2 "${additional_disk_args[@]}"
vm-mgr create -n $guest --force --disable --xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml -i $local_tmp_dir/system_"$guest"_"$fulldate".qcow2 "${additional_disk_args[@]}"
echo
echo creating base snapshots
for img in system_"$guest" $data_images
do
  echo rbd snap create "$img"@$fulldate
  rbd snap create "$img"@$fulldate
done
echo
for difffile in `ls $local_tmp_dir/*.diff 2>/dev/null`
do
  diffname=`basename $difffile .diff`
  # diff files are named <image>_<from date>_<to date>.diff
  image=`echo $diffname | sed -E "s/_[0-9]{12}_[0-9]{12}$//"`
  datediff=`echo $diffname | sed -e s/.*_//`
  if [ $datediff -le $incdate ]; then
    echo $difffile
    echo rbd import-diff $difffile rbd/$image
    rbd import-diff $difffile rbd/$image
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
