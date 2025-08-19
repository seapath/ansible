# Deploy Cockpit plugins Role

This role deploys the following cockpit plugins
* cockpit-cluster-dashboard
* cockpit-cluster-vm-management

## Requirements

No requirement.

## Role Variables

No variable.

## Example Playbook

```yaml
- name: deploy cockpit plugins
  hosts:
    - cluster_machines
  roles:
    - { role: seapath_ansible.deploy_cockpit_plugins }
```
