# Configure Libvirt Role

This role configure the libvirt secret and pool for ceph to use

## Requirements

no requirement.

## Role Variables

- libvirt_rbd_pool
- libvirt_pool_name

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
