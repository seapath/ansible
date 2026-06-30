# Cyclictest Role

This role runs cyclictest and fetch the resulting histogram.

## Requirements

no requirement.

## Role Variables

| Variable                 | Required | Type   | Default | Comments                               |
|--------------------------|----------|--------|---------|----------------------------------------|
| cyclictest_result_folder | No       | String | ..      | Path where cyclictest result is stored |
| cyclictest_duration      | No       | Int    | 20      | Duration of the test in seconds        |
| cyclictest_priority      | No       | Int    | 90      | Priority of the threads                |
| cyclictest_affinity      | No       | String | smp     | CPU affinity of the threads, if smp use `-S` |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cyclictest }
```
