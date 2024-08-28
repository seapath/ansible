# Network Resolved Role

This role configures the DNS with resolved

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network Resolved
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_resolved }
```
