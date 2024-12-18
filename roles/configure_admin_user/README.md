# Configure admin user Role
This role copy the root ssh key to admin user's. This user is used by Debian when using consolevm.

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type   | Comments                                                           |
|-------------------------|----------|--------|--------------------------------------------------------------------|
| seapath_distro          | yes      | String | SEAPATH variant. *CentOS*, *Debian* or *Yocto*. The variable can be set automatically using the *detect_seapath_distro role* |
| admin_user              | yes      | String | The admin user.                                                    |

## Example Playbook

```yaml
- name: Configure admin user
  hosts: hypervisors
  gather_facts: true
  become: true
  roles:
    - { role: seapath_ansible.configure_admin_user }
```
