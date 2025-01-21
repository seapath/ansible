# Network Guests br0 interfaces Role

This role creates the interfaces for guests which need to be on br0.

## Requirements

No requirement.

## Role Variables

| Variable              | Required  | Type | Comments |
|-----------------------|-----------|------|----------|
| interfaces_br0_netdev | No        | ???  | TODO     |
| interfaces_on_br0     | No        | ???  | TODO     |

## Example Playbook

```yaml
- name: Network Guests BR0 interfaces
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_guestsinterfaces }
```
