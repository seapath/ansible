# RedHat cukinia tests

This role deploys the tests specific to RedHat-family machines

## Requirements

No requirement.

## Role Variables

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.redhat_tests }
```
