#!/bin/bash
#
# Copyright (C) 2024 Savoir-faire Linux, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# This script detect the current rootfs partition and echo the associated efi
# partition. It is used to mount the active efi partition.

rootfs_part=$(mount | awk '/\/ / { print $1 }')
disk_name="${rootfs_part: : -1}"
part_num="${rootfs_part:(-1)}"

if [[ "${part_num}" == "3" ]] ; then
    bootloader_p="${disk_name}1"
else
    bootloader_p="${disk_name}2"
fi

echo $bootloader_p
