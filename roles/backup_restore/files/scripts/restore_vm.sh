#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
#
# Usage: restore_vm.sh <local_tmp_dir> <remote_shell> <remote_dir> <full backup dir> <guest> <inc date>
# e.g.: restore_vm.sh /data2/tmp "ssh -p 22" cephbackup@ip:/backups/ backup_ceph_202203110733 VM1 202203110836

set -u

local_tmp_dir=${1:-}
remote_shell=${2:-}
remote_dir=${3:-}
fulldatedir=${4:-}
guest=${5:-}
incdate=${6:-}

[ -z "$local_tmp_dir" ] && { echo "var local_tmp_dir empty"; exit 1; }
[ -z "$remote_shell" ] && { echo "var remote_shell empty"; exit 2; }
[ -z "$remote_dir" ] && { echo "var remote_dir empty"; exit 3; }
[ -z "$fulldatedir" ] && { echo "var fulldatedir empty"; exit 4; }
[ -z "$guest" ] && { echo "var guest empty"; exit 5; }
[ -z "$incdate" ] && { echo "var incdate empty"; exit 6; }

# Print the command before running it
function run {
  echo "$@"
  "$@"
}

echo "local_tmp_dir : $local_tmp_dir"
echo "remote_shell  : $remote_shell"
echo "remote_dir    : $remote_dir"
echo "fulldatedir   : $fulldatedir"
echo "guest         : $guest"
echo "incdate       : $incdate"

fulldate=${fulldatedir#backup_ceph_}

echo Removing tmp local dir
echo "rm -rf $local_tmp_dir/*, press enter to proceed"
read -r
rm -rf "${local_tmp_dir:?}"/*
echo
echo copying files locally
run rsync -ave "$remote_shell" --progress "$remote_dir$fulldatedir/*_${guest}-*" "$local_tmp_dir/"
run rsync -ave "$remote_shell" --progress "$remote_dir$fulldatedir/*_${guest}_*" "$local_tmp_dir/"
echo
echo creating vm xml with no disk
run python3 /usr/local/bin/remove_disk_xml.py "$local_tmp_dir/system_$guest-$incdate.xml" "$local_tmp_dir/system_$guest-$incdate-nodisk.xml"
echo
# Additional disks (data_<guest>_<n>) are restored from their full backup
# qcow2, in index order so vm-mgr recreates them under their original names
data_images=$(cd "$local_tmp_dir" && ls data_"$guest"_*_"$fulldate".qcow2 2>/dev/null | sed -e "s/_$fulldate\.qcow2$//" | sort -t_ -k3 -n)
additional_disk_args=()
for img in $data_images
do
  additional_disk_args+=(--additional-disk "$local_tmp_dir/${img}_${fulldate}.qcow2")
done
echo creating base vm
run vm-mgr create -n "$guest" --force --disable --xml "$local_tmp_dir/system_$guest-$incdate-nodisk.xml" \
    -i "$local_tmp_dir/system_${guest}_${fulldate}.qcow2" "${additional_disk_args[@]}"
echo
echo creating base snapshots
for img in system_"$guest" $data_images
do
  run rbd snap create "$img@$fulldate"
done
echo
for difffile in "$local_tmp_dir"/*.diff
do
  [ -e "$difffile" ] || continue
  diffname=$(basename "$difffile" .diff)
  # diff files are named <image>_<from date>_<to date>.diff
  image=$(echo "$diffname" | sed -E "s/_[0-9]{12}_[0-9]{12}$//")
  datediff=${diffname##*_}
  if [ "$datediff" -le "$incdate" ]; then
    run rbd import-diff "$difffile" "rbd/$image"
  fi
done
echo
echo Restoring metadata
for metafile in "$local_tmp_dir"/system_"$guest"-meta-*-"$incdate".txt
do
  [ -e "$metafile" ] || continue
  key=$(basename "$metafile" "-${incdate}.txt")
  key=${key#system_${guest}-meta-}
  echo "metadata name = $key"
  run rbd image-meta set "system_$guest" "$key" "$(cat "$metafile")"
done
echo
echo Starting VM
run vm-mgr enable -n "$guest"
