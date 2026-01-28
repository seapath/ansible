# Configure Libvirt Role

This enables and starts the libvirtd service and associated socket.

Also, if `configure_libvirt_allow_non_root_libvirt_socket_access` is set to
true, this role configures the Libvirt socket to be accessible by non-root users
when they are in the libvirt group.
This is useful for the Libvirt administration user to
- Provide live migration over the cluster
- Allow VM console access over the cluster

## Requirements

No requirement.

## Role Variables

| Variable                                               | Required | Type    | Default | Comments                                                                                   |
|--------------------------------------------------------|----------|---------|---------|--------------------------------------------------------------------------------------------|
| configure_libvirt_allow_non_root_libvirt_socket_access | no       | Boolean | true    | Allow non-root users in libvirt group to access libvirt socket                             |

## Example Playbook

```yaml
- hosts: hypervisors
  become: true
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
