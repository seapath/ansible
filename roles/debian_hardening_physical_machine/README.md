# Debian Hardening for Physical Machine Role

This role apply the hardening configurations for debian physical machines.

## Requirements

No requirement.

## Role Variables

| Variable      | Type   | Comments                                                        |
|---------------|--------|-----------------------------------------------------------------|
| ceph_osd_disk | String | Node device disk to use for Ceph OSD if lvm_volumes is not used |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_hardening_physical_machine }
```
