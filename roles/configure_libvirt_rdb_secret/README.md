# Configure Libvirt Role

This role create a libvirt storage pool for ceph.

## Requirements

No requirement.

## Role Variables

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
