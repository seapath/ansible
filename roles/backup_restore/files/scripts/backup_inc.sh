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

# Container workloads, as backup_full.sh selects them.
LIST_CONTAINERS=$( python3 /usr/local/bin/get_containers.py | grep -E "($include_vm)" | grep -E -v "($exclude_vm)" )

# The snapshots the backups took of an image, named after a minute and
# nothing else.
function backup_snapshots {
  rbd snap ls "rbd/$1" | awk 'NR > 1 { print $2 }' | grep -E '^[0-9]{12}$' | sort
}

# The container images a workload runs, as deploy_containers_cluster recorded
# them in seapath.images. With the definition the role records in the
# metadata, they make a backup enough to deploy the workload on a cluster
# that never had it. Saved under images/, one file per image, and a file
# already there is not saved again: once per full backup, and an incremental
# backup adds the images a new version brought.
function save_images {
  mkdir -p "$2/images"
  for image in $(rbd image-meta get "rbd/$1" seapath.images 2> /dev/null)
  do
    file="$2/images/$(echo "$image" | tr '/:@' '___').tar"
    [ -e "$file" ] && continue
    echo "    $image"
    if ! podman image save --format docker-archive -o "$file" "$image"; then
      rm -f "$file"
      echo "WARNING: $image is not on this node, and is not in the backup of $1"
    fi
  done
}

echo "Include (guests and containers) : $include_vm"
echo "Exclude (guests and containers) : $exclude_vm"
echo "------------------------------------"
echo "List of Guests to backup: " $LIST_GUESTS
echo "List of Containers to backup: " $LIST_CONTAINERS
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
# A workload's diff is taken against the latest snapshot of a backup, and
# never against one deploy_containers_cluster took before a new version,
# which no backup holds and a restore could not replay the diff onto.
for name in $LIST_CONTAINERS
do
  echo "container $name"
  c="$latest_full/containers/$name"
  latest=$(backup_snapshots "$name" | tail -n 1)
  if [ -z "$latest" ] || [ ! -d "$c" ]; then
    echo "WARNING: rbd/$name is not part of the latest full backup and cannot be backed up incrementally"
    not_in_full="$not_in_full $name"
    continue
  fi
  echo creating new snapshot
  rbd snap create "rbd/$name@$d"
  echo creating diff
  rbd export-diff --from-snap "$latest" "rbd/$name@$d" "$c/${latest}_${d}.diff"
  echo backuping metadata
  rbd image-meta list "rbd/$name" --format json > "$c/$d.json"
  echo backuping the container images
  save_images "$name" "$c"
done
if [ -n "$not_in_full" ]; then
  echo "------------------------------------"
  echo "WARNING: the following disks are missing from the latest full backup"
  echo "and were NOT backed up:$not_in_full"
  echo "Run a new full backup to include them."
  echo "------------------------------------"
fi
rsync -ave "$remote_shell" --progress "$latest_full" "$remote_dir"
