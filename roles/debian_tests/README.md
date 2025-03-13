# Deploy cukinia tests Role

This role deploys the cukinia tests for Debian

## Requirements

No requirement.

## Role Variables

No variable.

## Example Playbook

```yaml
- name: deploy cukinia tests
  hosts:
    - cluster_machines
    - standalone_machine
    - VMs
  become: true
  roles:
    - { role: seapath_ansible.debian_tests, filter: "none" }
```
