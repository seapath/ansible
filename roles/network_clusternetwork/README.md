# Cluster Network Role

This role configures the cluster network

## Requirements

no requirement.

## Role Variables

no variable.

## Example Playbook

```yaml
- name: Configure Cluster Network
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.network_clusternetwork }
```
