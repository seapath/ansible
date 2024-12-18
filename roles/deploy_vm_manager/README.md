# Deploy vm_manager Role

This role deploys the vm_manager utility

## Requirements

No requirement.

## Role Variables

No variable.

## Example Playbook

```yaml
- name: deploy vm_manager
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.deploy_vm_manager }
```
