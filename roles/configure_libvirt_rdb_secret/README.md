# Configure Libvirt Role

This role create a libvirt storage pool for ceph.

## Requirements

No requirement.

## Role Variables

| Variable                           | Required | Type   | Default | Comments                                       |
|------------------------------------|----------|--------|---------|------------------------------------------------|
| configure_libvirt_libvirt_rbd_pool | no       | String | rbd     | The Ceph RBD pool use by libvirts              |
| configure_libvirt_libvirt_pool_name| no       | String | ceph    | The name of the libvirt storage pool to create |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
