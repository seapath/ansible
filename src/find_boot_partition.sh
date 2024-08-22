#!/bin/bash

rootfs_part=$(mount | awk '/\/ / { print $1 }')
disk_name="${rootfs_part: : -1}"
part_num="${rootfs_part:(-1)}"

if [[ "${part_num}" == "3" ]] ; then
    bootloader_p="${disk_name}1"
else
    bootloader_p="${disk_name}2"
fi

echo $bootloader_p
