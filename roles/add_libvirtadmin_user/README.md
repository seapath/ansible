# Add Libvirt administration user role

This role set up the Libvirt administration user on the cluster and configure
its ssh key exchanges.
If the user does not already exist, it will be created.
The user is named "libvirtadmin"

## Requirements

No requirement.

## Role Variables

No variables.

## Example Playbook

```yaml
- name: Create libvirtadmin user
  hosts: hypervisors
  gather_facts: true
  become: true
  roles:
    - { role: seapath_ansible.add_libvirtadmin_user }
```
