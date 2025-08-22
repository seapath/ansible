# Deploy Cockpit plugins Role

This role deploys the following cockpit plugins
* cockpit-cluster-dashboard
* cockpit-cluster-vm-management

## Requirements

No requirement.

## Role Variables

| Variable        | Required  | Type   | Default | Comments                                              |
|-----------------|-----------|--------|-----------------------------------------------------------------|
| cockpit_plugins | No        | Bool   | false   | Install cockpit plugins                               |


## Example Playbook

```yaml
- name: deploy cockpit plugins
  hosts:
    - cluster_machines
  roles:
    - { role: seapath_ansible.deploy_cockpit_plugins }
```
