# Hardening for Physical Machine Role

This role applies the hardening configurations for physical machines.

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
    - { role: seapath_ansible.configure_hardening_physical_machine }
```
