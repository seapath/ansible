# CI restore snapshot Role

This role restores the LVM snapshot of the root LV and re-creates it

## Requirements

No requirement.

## Role Variables

No variable.

## Example Playbook

```yaml
- name: CI restore snapshot
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.ci_restore_snapshot }
```
