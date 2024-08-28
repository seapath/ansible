# Network Netplan Role

This role configures the network via Netplan

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network Netplan
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_netplan }
```
