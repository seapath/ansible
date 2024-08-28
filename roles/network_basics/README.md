# Network Basics Role

This role does the basic network stuff, cleaning and setting defaults

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network Basics
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_basics }
```
