# Configure admin_user Role
This role copy the root ssh key to admin user's. This user is used by Debian when using consolevm.

## Requirements

- detect_seapath_distro

## Role Variables

- admin_user

## Example Playbook

```yaml
- name: Configure admin user
  hosts: hypervisors
  gather_facts: true
  become: true
  roles:
    - { role: seapath_ansible.configure_admin_user }
```
