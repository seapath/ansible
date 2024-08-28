# Network Basics Role

This role builds the host and hostname files

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network Build Hosts
  hosts:
    - cluster_machines
    - standalone_machine
  roles:
    - { role: seapath_ansible.network_buildhosts }
```
