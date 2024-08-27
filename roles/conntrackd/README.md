# Conntrackd Role

This role configure the conntrackd feature

## Requirements

no requirement.

## Role Variables

- conntrackd_ignore_ip_list

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.conntrackd }
```
