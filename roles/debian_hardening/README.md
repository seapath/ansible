# Debian Hardening Role

This role apply the hardening SEAPATH configurations

## Requirements

no requirement.

## Role Variables

- sudoers_files
- admin_user
- hardened_services
- grub_password
- ip_addr
- cluster_ip_addr

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_hardening }
```
