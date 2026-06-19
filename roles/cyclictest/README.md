# Cyclictest Role

This role runs cyclictest and fetch the resulting histogram.

## Requirements

no requirement.

## Role Variables

| Variable            | Required | Type   | Default | Comments                               |
|---------------------|----------|--------|---------|----------------------------------------|
| cukinia_test_prefix | No       | String | ..      | Path where cyclictest result is stored |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cyclictest }
```
