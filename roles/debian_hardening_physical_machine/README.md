# Debian Hardening for Physical Machine Role

This role apply the hardening configurations for debian physical machines

## Requirements

no requirement.

## Role Variables

- hardened_services
- ceph_osd_disk

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_hardening_physical_machine }
```
