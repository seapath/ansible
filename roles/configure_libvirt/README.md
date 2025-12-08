# Configure Libvirt Role

This role if `configure_libvirt_allow_non_root_libvirt_socket_access` is set to
true or a `livemigration_user` is defined, configure the libvirt socket to be
 accessible by non-root users if they are in the libvirt group.

This role also enable and starts the libvirtd service and associated socket and
services.

## Requirements

No requirement.

## Role Variables

| Variable                                               | Required | Type    | Default | Comments                                                                                   |
|--------------------------------------------------------|----------|---------|---------|--------------------------------------------------------------------------------------------|
| configure_libvirt_allow_non_root_libvirt_socket_access | no       | Boolean | true    | Allow non-root users in libvirt group to access libvirt socket                             |
| livemigration_user                                     | no       | String  | null    | The user used for live migrate VM. If defined, it allows non-root access to libvirt socket |

## Example Playbook

```yaml
- hosts: hypervisors
  become: true
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
