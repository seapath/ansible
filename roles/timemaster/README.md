# Timemaster Role

This role configures timemaster

## Requirements

no requirement.

## Role Variables

no variable.

## Example Playbook

```yaml
- name: Configure Timemaster
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.timemaster }
```
