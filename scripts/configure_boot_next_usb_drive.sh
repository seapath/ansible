#!/bin/sh

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root"
  exit 1
fi

if [ ! -d /sys/firmware/efi/efivars ]; then
  echo "Please run on an EFI system"
  exit 1
fi

if ! mount |grep -q /sys/firmware/efi/efivars; then
    mount -t efivarfs efivarfs /sys/firmware/efi/efivars || exit 1
fi

usb_boot=$(efibootmgr |grep -i USB |cut -d ' ' -f 1  |grep -Eo '[0-9]+')
if [ -z "${usb_boot}" ]; then
    echo "No USB boot option found"
    exit 1
fi

if efibootmgr |grep -q "BootNext: ${usb_boot}" ; then
    echo "USB boot option already set"
    exit 2
fi

efibootmgr -n "${usb_boot}" || exit 1
