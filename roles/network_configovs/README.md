# network configovs Role

This role configures OVS

## Requirements

- detect_seapath_distro

## Role Variables

no variable.

## Example Playbook

```yaml
- name: Configure OVS
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.network_configovs }
```
