# Deploy cukinia Role

This role deploys the cukinia utility

## Requirements

no requirement.

## Role Variables

no variable.

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
