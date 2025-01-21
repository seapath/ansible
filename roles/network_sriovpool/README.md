# Network SR-IOV pool Role

This role creates a libvirt pool for an SR-IOV interface.

## Requirements

No requirement.

## Role Variables

| Variable                | Required  | Type   | Comments                                  |
|-------------------------|-----------|--------|-------------------------------------------|
| sriov_network_pool_name | Yes       | String | Name of the libvirt SR-IOV pool           |
| interface               | Yes       | String | Network interface to use for SR-IOV setup |

## Example Playbook

```yaml
- name: Network SR-IOV libvirt pool
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_sriovpool }
```
