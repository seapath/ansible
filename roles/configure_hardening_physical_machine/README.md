# Hardening for Physical Machine Role

This role applies the hardening configurations for physical machines.

## Requirements

No requirement.

## Role Variables

| Variable      | Type   | Comments                                                        |
|---------------|--------|-----------------------------------------------------------------|
| ceph_osd_disks | List | Paths of the block devices given to Ceph OSDs on this node |
| ceph_osd_disk | String | Shorthand for a one-element ceph_osd_disks list |
| configure_hardening_physical_machine_snmp_user_name | String | SNMP user |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_hardening_physical_machine }
```
