# OracleLinux Role

This role apply the basic SEAPATH prerequisites for any OracleLinux machine

## Requirements

no requirement.

## Role Variables

| Variable             | Required | Type        | Comments                                                           |
|----------------------|----------|-------------|--------------------------------------------------------------------|
| admin_user           |  Yes     | String      | User to use for administration                                     |
| admin_passwd         |  No      | String      | Optional user password                                             |
| admin_ssh_keys       |  No      | String list | List of SSH public keys used to connect to the administration user |
| grub_append          |  No      | String list | List of extra kernel parameters                                    |
| apt_repo             |  No      | String list | List of apt repositories                                           |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.oraclelinux }
```
