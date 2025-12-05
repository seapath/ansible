# Configure Libvirt Role

This role create a libvirt storage pool for ceph and configure the livirt socket
to be accessible by non-root users if there are in the libvirt group.

In cluster this role should be applied after Ceph has been configured.

## Requirements

No requirement.

## Role Variables

| Variable                           | Required | Type   | Default | Comments                                       |
|------------------------------------|----------|--------|---------|------------------------------------------------|
| configure_libvirt_libvirt_rbd_pool | no       | String | rbd     | The Ceph RBD pool use by libvirts              |
| configure_libvirt_libvirt_pool_name| no       | String | ceph    | The name of the libvirt storage pool to create |
| configure_libvirt_allow_non_root_libvirt_socket_access | no | Boolean | true | Allow non-root users in libvirt group to access libvirt socket |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
