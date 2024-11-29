# Timemaster Role

This role configures timemaster

## Requirements

- detect_seapath_distro

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
