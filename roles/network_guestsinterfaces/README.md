# Network Guests br0 interfaces Role

This role creates the interfaces for guests which need to be on br0

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network Guests BR0 interfaces
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_guestsinterfaces }
```
