#!/bin/bash

local_tmp_dir=$1
remote_dir=$2
fulldatedir=$3
guest=$4
incdate=$5

[ -z "$local_tmp_dir" ] && { echo "var local_tmp_dir empty"; exit 1; }
[ -z "$remote_dir" ] && { echo "var remote_dir empty"; exit 2; }
[ -z "$fulldatedir" ] && { echo "var fulldatedir empty"; exit 3; }
[ -z "$guest" ] && { echo "var guest empty"; exit 4; }
[ -z "$incdate" ] && { echo "var incdate empty"; exit 5; }

f="$local_tmp_dir""$d"
mkdir -p $f

#called with : ./restore_vm.sh /data2/tmp cephbackup@ip:/mnt/nasopf/seapath/backups_ceph_cluster_lot1/ backup_ceph_202203110733 VM1 202203110836
#local_tmp_dir=/data2/tmp
#remote_dir=cephbackup@ip:/mnt/nasopf/seapath/backups_ceph_cluster/
#fulldatedir=backup_ceph_202203110733
#guest=VM2
#incdate=202203110836

echo $local_tmp_dir
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
echo rsync -ave ssh --progress $remote_dir$fulldatedir/*$guest* $local_tmp_dir/
rsync -ave ssh --progress $remote_dir$fulldatedir/*$guest* $local_tmp_dir/
echo
echo creating vm xml with no disk
echo python3 /usr/bin/remove_disk_xml.py $local_tmp_dir/system_"$guest"-"$incdate".xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml
python3 /usr/bin/remove_disk_xml.py $local_tmp_dir/system_"$guest"-"$incdate".xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml
echo
echo creating base vm
echo vm-mgr create -n $guest --force --disable --enable-live-migration --migration-user virtu --xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml -i $local_tmp_dir/system_"$guest"_"$fulldate".qcow2
vm-mgr create -n $guest --force --disable --enable-live-migration --migration-user virtu --xml $local_tmp_dir/system_"$guest"-"$incdate"-nodisk.xml -i $local_tmp_dir/system_"$guest"_"$fulldate".qcow2
echo
echo creating base snapshot
echo rbd snap create system_"$guest"@$fulldate
rbd snap create system_"$guest"@$fulldate
echo
for difffile in `ls /data2/tmp/*.diff`
do
  datediff=`echo $difffile | sed -e s/.*_// -e s/\.diff//` 
  if [ $datediff -le $incdate ]; then
    echo $difffile
    echo rbd import-diff $difffile rbd/system_"$guest"
    rbd import-diff $difffile rbd/system_"$guest"
  fi
done
echo
echo Starting VM
echo vm-mgr enable -n $guest
vm-mgr enable -n $guest
exit

