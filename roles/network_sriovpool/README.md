# Network SR-IOV pool Role

This role creates a libvirt pool for an SR-IOV interface

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network SR-IOV libvirt pool
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_sriovpool }
```
