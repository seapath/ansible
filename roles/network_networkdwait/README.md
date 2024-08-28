# Network Networkd Wait Role

This role configure the networkd wait service

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network Networkd Wait
  hosts:
    - cluster_machines
    - standalone_machine
  roles:
    - { role: seapath_ansible.network_networkdwait }
```
