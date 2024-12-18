# Deploy cukinia Role

This role deploys the cukinia utility

## Requirements

No requirement.

## Role Variables

No variable.

## Example Playbook

```yaml
- name: deploy cukinia
  hosts:
    - cluster_machines
    - standalone_machine
    - VMs
  become: true
  roles:
    - { role: seapath_ansible.deploy_cukinia }
```
