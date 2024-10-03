# Network Mesh Role

This role creates a wifi mesh network for the cluster network

## Requirements

no requirement.

## Role Variables

no variables.

## Example Playbook

```yaml
- name: Network Mesh
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_mesh }
```
