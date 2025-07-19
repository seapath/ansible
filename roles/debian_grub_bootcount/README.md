# Debian Grub Boot Count Role

This role sets up a process to automatically restore a "working" setup of a server after a problematic upgrade.

On every major update, a snapshot of the "root" LV is taken (on SEAPATH Debian, it includes the whole rootfs, /boot included).

- Boot count is stored as a Grub environement file in ESP: /boot/efi/bootcountenv.
- The boot count is incremented each boot by `11_seapath_boot_count`.
- On successful boot (measured by system_check.service based on systemctl is-system-running), boot counting is disabled and the default boot process is used (lasted kernel first).
- On the 3rd unsuccessful boot in a row, the LVM snapshot on the root LV is recovered and the system rebooted, effectively reverting any update done since the snapshot (kernel update included).

The recovery process is implemented using initramfs scripts run by a "safe" kernel (second to last or the unique kernel).

Known limitations:
* This implementation is tied to the default configuration (disk partitioning, LV naming, ...)
* The recovery won't work if the "safe" kernel refuses to boot.

## Requirements

no requirement.

## Role Variables

| Variable              | Type    | Comments                                                                       |
|-----------------------|---------|--------------------------------------------------------------------------------|
| debian_grub_bootcount | Boolean | When set to false, the role will the setup of the grub bootcount mechanism     |
|                       |         | When set to true, this will rollback the setup of the grub bootcount mechanism |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_grub_bootcount }
```
