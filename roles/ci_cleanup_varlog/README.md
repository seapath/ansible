# Cleanup /var/log/ Role

This role removes the content of the /var/log/ folder

## Requirements

no requirement.

## Role Variables

no variable.

## Example Playbook

```yaml
- name: Cleanup /var/log/ folder
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.ci_cleanup_varlog }
```
