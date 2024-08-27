# CI restore snapshot Role

This role restores the LVM snapshot of the root LV and re-creates it

## Requirements

no requirement.

## Role Variables

- grub_append

## Example Playbook

```yaml
- name: CI restore snapshot
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.ci_restore_snapshot }
```
