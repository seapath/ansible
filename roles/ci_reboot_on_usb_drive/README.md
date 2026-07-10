# CI Reboot On USB driver

This role reboots the CI machine on the USB key.
This key will then automatically flash the machine with a new image.

## Requirements

No requirement.

## Role Variables

## Example Playbook

```yaml
- hosts: standalone_machine
  roles:
    - { role: seapath_ansible.ci_reboot_on_usb_drive }
```
