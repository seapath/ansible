# Deploy cukinia tests Role

This role deploys the cukinia tests

## Requirements

no requirement.

## Role Variables

- filter (can be "none", "hosts", "observers" or "guests")

## Example Playbook

```yaml
- name: deploy cukinia tests
  hosts:
    - cluster_machines
    - standalone_machine
    - VMs
  become: true
  roles:
    - { role: seapath_ansible.deploy_cukinia_tests, filter: "none" }
```
