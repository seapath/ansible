#!/bin/bash
# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0
#
# Usage: restore_container.sh <local_tmp_dir> <remote_shell> <remote_dir> <full backup dir> <workload> <date>
# e.g.: restore_container.sh /data2/tmp "ssh -p 22" cephbackup@ip:/backups/ 202203110733 nginx 202203110836
#
# Brings back the RBD image of a container workload of deploy_containers_cluster,
# the state the workload wrote, as it was at <date>, with the metadata of that
# date, which hold the definition deploy_containers_cluster recorded. Its
# quadlets, images and configuration on the nodes are not touched: a workload
# whose version changed since then reads the state of the version it had. The
# images the backup saved are left in <local_tmp_dir>/images, and the
# definition in the metadata, for a workload to be declared again from them.
#
# The workload is stopped, its current image is put aside as
# <workload>.<date>-restore, the way the role puts it aside when it recreates
# a workload and with the same pruning, and the workload is started again
# unless it was stopped already. A workload with no Pacemaker resource yet, on
# a cluster being rebuilt, gets its image, and deploy_containers_cluster then
# keeps it rather than creating an empty one.

# -E so that the ERR trap set below also fires inside run
set -eEu

local_tmp_dir=${1:-}
remote_shell=${2:-}
remote_dir=${3:-}
fulldatedir=${4:-}
name=${5:-}
incdate=${6:-}

[ -z "$local_tmp_dir" ] && { echo "var local_tmp_dir empty"; exit 1; }
[ -z "$remote_shell" ] && { echo "var remote_shell empty"; exit 2; }
[ -z "$remote_dir" ] && { echo "var remote_dir empty"; exit 3; }
[ -z "$fulldatedir" ] && { echo "var fulldatedir empty"; exit 4; }
[ -z "$name" ] && { echo "var workload empty"; exit 5; }
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
echo "workload      : $name"
echo "incdate       : $incdate"

# The names deploy_containers_cluster accepts
if [[ ! $name =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]]; then
  echo "$name is not a workload name"
  exit 7
fi
if [[ $fulldatedir =~ ([0-9]{12})/?$ ]]; then
  fulldate=${BASH_REMATCH[1]}
else
  echo "no date at the end of $fulldatedir"
  exit 7
fi

echo Removing tmp local dir
echo "rm -rf $local_tmp_dir/*, press enter to proceed"
read -r
rm -rf "${local_tmp_dir:?}"/*
echo
echo copying files locally
run rsync -ave "$remote_shell" --progress "$remote_dir$fulldatedir/containers/$name/" "$local_tmp_dir/"
[ -e "$local_tmp_dir/$fulldate.qcow2" ] || { echo "the backup of $fulldate holds no image of $name"; exit 8; }
[ -e "$local_tmp_dir/$incdate.json" ] || { echo "the backup of $fulldate holds nothing of $name at $incdate"; exit 8; }
echo

resource=no
target_role=""
if crm configure show "$name" > /dev/null 2>&1; then
  resource=yes
  target_role=$(crm_resource --resource "$name" --meta --get-parameter target-role 2> /dev/null || true)
  echo "Stopping $name"
  # --wait returns once the transition is over: the units are stopped and
  # the RBD image is unmounted and unmapped on the node that ran it.
  run crm --wait resource stop "$name"
fi

aside=""
if rbd info "rbd/$name" > /dev/null 2>&1; then
  # rbd mv does not refuse a mapped image: a node still using it would go on
  # writing to the image put aside.
  watchers=$(rbd status "rbd/$name" --format json | python3 -c 'import json, sys; print(len(json.load(sys.stdin).get("watchers", [])))')
  if [ "$watchers" != 0 ]; then
    echo "rbd/$name is still used by a node: the image was not touched, and $name is left stopped"
    exit 9
  fi
  aside="$name.$(date -u +%Y%m%dT%H%M%SZ)-restore"
  echo "Putting the current image aside"
  run rbd mv "rbd/$name" "rbd/$aside"
  trap 'echo "The restore failed. The image $name had before it is rbd/$aside."' ERR
fi
echo

# Created as seapath-rbd-mount creates it, with the features a kernel mapping
# needs, and the size it had.
size=$(qemu-img info --output json "$local_tmp_dir/$fulldate.qcow2" | python3 -c 'import json, sys; print(json.load(sys.stdin)["virtual-size"])')
echo creating the image
run rbd create "rbd/$name" --size "$(( (size + 1048575) / 1048576 ))M" --image-feature layering
run qemu-img convert -n -f qcow2 -O raw "$local_tmp_dir/$fulldate.qcow2" "rbd:rbd/$name"
run rbd snap create "rbd/$name@$fulldate"
echo
# diff files are named <from date>_<to date>.diff
for difffile in "$local_tmp_dir"/*.diff
do
  [ -e "$difffile" ] || continue
  datediff=$(basename "$difffile" .diff)
  datediff=${datediff##*_}
  if [ "$datediff" -le "$incdate" ]; then
    run rbd import-diff "$difffile" "rbd/$name"
  fi
done
echo
echo Restoring metadata
# The definition deploy_containers_cluster records there can exceed what one
# argument of `rbd image-meta set` may hold.
run python3 /usr/local/bin/restore_metadata.py "rbd/$name" "$local_tmp_dir/$incdate.json"
trap - ERR
echo
if [ "$resource" = yes ] && [ "$target_role" != Stopped ]; then
  echo "Starting $name"
  run crm --wait resource start "$name"
fi
[ -n "$aside" ] && echo "The image $name had before the restore is rbd/$aside."
[ -d "$local_tmp_dir/images" ] && echo "The images $name ran are in $local_tmp_dir/images, for podman load."
exit 0
