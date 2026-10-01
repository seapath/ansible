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

# Guests are identified by their system disk (system_<guest>). Their
# additional disks (data_<guest>_<n>) are backed up along with them.
LIST_GUESTS=$( rbd list | grep -E "^system_" | sed -e "s/^system_//" | grep -E "($include_vm)" | grep -E -v "($exclude_vm)" )

# Container workloads (deploy_containers_cluster) keep what they write on an
# RBD image named after them, and their definition (entry, quadlets,
# configuration) in its metadata, as a guest keeps its XML; the images they
# run are saved beside it. The two filters apply to their names as to guest names: a
# workload and a guest are both a Pacemaker resource, and share one namespace.
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
echo Removing old full backups local dirs
echo "rm -rf ${local_dir}*, press enter to proceed"
read -r
rm -rf "${local_dir:?}"*

d=$(date +%Y%m%d%H%M)
f="$local_dir$d"
mkdir -p "$f"
for guest in $LIST_GUESTS
do
  images="system_$guest $(rbd list | grep -E "^data_${guest}_[0-9]+$")"
  for i in $images
  do
    echo "$i"
    echo sparsifying
    rbd sparsify "$i"
    echo purging snapshots
    rbd snap purge "rbd/$i"
    echo creating base snapshot
    rbd snap create "rbd/$i@$d"
    echo backuping snapshot
    qemu-img convert -f raw -O qcow2 "rbd:rbd/$i@$d" "$f/${i}_$d.qcow2"
  done
  i=system_$guest
  echo backuping vm xml
  rbd image-meta get "rbd/$i" xml > "$f/$i-$d.xml"
  echo backuping metadata all
  rbd image-meta list "rbd/$i" > "$f/$i-metaall-$d.txt"
  echo backuping metadata one by one
  for j in $(python3 /usr/local/bin/get_metadata.py "$guest")
  do
    echo "    $j"
    rbd image-meta get "rbd/$i" "$j" > "$f/$i-meta-$j-$d.txt"
  done
  echo ----
done
# A workload's image goes under containers/<name>/, where nothing matches the
# patterns a guest's restore downloads with. Only the snapshots of previous
# backups are removed: the ones deploy_containers_cluster takes before a new
# version are what a rollback to that version needs. It is not sparsified, a
# saving in the pool the qcow2 export does not need. The workload runs
# meanwhile, so the snapshot holds what a power cut would leave, as the
# role's own snapshots do.
for name in $LIST_CONTAINERS
do
  echo "container $name"
  c="$f/containers/$name"
  mkdir -p "$c"
  echo removing the snapshots of previous backups
  for s in $(backup_snapshots "$name")
  do
    rbd snap rm "rbd/$name@$s"
  done
  echo creating base snapshot
  rbd snap create "rbd/$name@$d"
  echo backuping snapshot
  qemu-img convert -f raw -O qcow2 "rbd:rbd/$name@$d" "$c/$d.qcow2"
  echo backuping metadata
  rbd image-meta list "rbd/$name" --format json > "$c/$d.json"
  echo backuping the container images
  save_images "$name" "$c"
  echo ----
done
rsync -ave "$remote_shell" --progress "$f" "$remote_dir"
