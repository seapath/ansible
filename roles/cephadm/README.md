# cephadm Role

This role deploys ceph using cephadm (instead of ceph-ansible)

## Requirements

no requirement.

## Role Variables

no variable.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cephadm }
```
