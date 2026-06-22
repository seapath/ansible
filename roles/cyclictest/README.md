# Cyclictest Role

This role runs cyclictest and fetch the resulting histogram.

## Requirements

no requirement.

## Role Variables

| Variable                 | Required | Type   | Default | Comments                               |
|--------------------------|----------|--------|---------|----------------------------------------|
| cyclictest_result_folder | No       | String | ..      | Path where cyclictest result is stored |
| cyclictest_duration      | No       | Int    | 20      | Duration of the test in seconds        |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cyclictest }
```
