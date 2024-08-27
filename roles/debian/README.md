# Debian Role

This role apply the basic SEAPATH prerequisites for any debian machine

## Requirements

no requirement.

## Role Variables

- syslog_tls_ca
- syslog_tls_key
- syslog_tls_server_ca
- admin_user
- admin_passwd
- admin_ssh_keys
- grub_append
- syslog_server_ip
- apt_repo

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian }
```
