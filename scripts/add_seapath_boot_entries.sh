#!/bin/bash
# Copyright (C) 2022, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0


if [ $# -gt 1 ] ; then
    echo "Error $0 takes no arguments" 1>&2
    exit 3
fi

if [ ! -d /sys/firmware/efi/efivars ] ; then
    echo "No EFI system"
    exit 0
fi

echo "EFI image."
active_boot=$(efibootmgr | awk '/SEAPATH slot 0/{ gsub("Boot", ""); gsub("*", ""); print $1 }')
passive_boot=$(efibootmgr | awk '/SEAPATH slot 1/{ gsub("Boot", ""); gsub("*", ""); print $1 }')
if [ -n "$active_boot" ] && \
   efibootmgr | grep "$active_boot" | cut -d ' ' -f 1 | grep -q '*' && \
   [ -n "$passive_boot" ] && \
   efibootmgr | grep "$active_boot" | cut -d ' ' -f 1 | grep -vq '*' ; then
        echo "Boot entries already defined"
        exit 0
fi
root_part=$(mount | grep ' / ' | cut -d ' ' -f 1)
disk=/dev/$(lsblk -ndo pkname "$root_part")

if [ -z "$passive_boot" ] ;  then
    command="efibootmgr -q -c -d \"$disk\" -p 2 -L \"SEAPATH slot 1\" -l /EFI/BOOT/bootx64.efi"
    if eval "$command" ; then
        echo "Entry SEAPATH slot 1 successfully created"
    else
        echo "Error while creating entry SEAPATH slot 1"
        exit 1
    fi
fi

if [ -z "$active_boot" ] ;  then
    command="efibootmgr -q -c -d \"$disk\" -p 1 -L \"SEAPATH slot 0\" -l /EFI/BOOT/bootx64.efi"
    if eval "$command" ; then
        echo "Entry SEAPATH slot 0 successfully created"
    else
        echo "Error while creating entry SEAPATH slot 0"
        exit 1
    fi
fi


# Disable slot 1
passive_boot=$(efibootmgr | awk '/SEAPATH slot 1/{ gsub("Boot", ""); gsub("*", ""); print $1 }')
if efibootmgr -q -b "${passive_boot}" -A ; then
    echo "Entry ${passive_boot} sucessfully disabled"
else
    echo "Error while disabling entry ${passive_boot}"  1>&2
    exit 1
fi

# Enable slot 1
active_boot=$(efibootmgr | awk '/SEAPATH slot 0/{ gsub("Boot", ""); gsub("*", ""); print $1 }')
if efibootmgr -q -b "${active_boot}" -a ; then
    echo "Entry ${active_boot} sucessfully disabled"
else
    echo "Error while disabling entry ${active_boot}"  1>&2
    exit 1
fi

echo "Move SEAPATH boot at the end of the boot order"
echo "Disable all unwanted boot entries in UEFI setup or with the efibootmgr"
echo "command"

# Set top boot order priority for USB and PXE entries
boot_order=$(efibootmgr | grep "BootOrder" | awk '{ print $2}')

# Remove SEAPATH entries from bootOrder
boot_order=$(echo "$boot_order" | sed "s/$active_boot//")
boot_order=$(echo "$boot_order" | sed "s/$passive_boot//")

# Remove unwanted commas
boot_order=$(echo "$boot_order" | sed "s/,,/,/")
boot_order=$(echo "$boot_order" | sed 's/,$//')
boot_order=$(echo "$boot_order" | sed 's/^,//')

# Add SEAPATH entries at the end
boot_order="$boot_order,$active_boot,$passive_boot"

# Change boot order
if efibootmgr -q -o "$boot_order" ; then
    echo "Boot order successfully changed"
else
    echo "Error while changing boot order"
    exit 1
fi
echo "Set the next reboot to be on SEAPATH slot 0"
efibootmgr --bootnext "$active_boot"
efibootmgr

exit 2
