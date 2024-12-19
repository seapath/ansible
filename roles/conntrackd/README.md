# Conntrackd Role

This role configure the conntrackd feature

## Requirements

No requirement.

## Role Variables

- conntrackd_ignore_ip_list

| Variable                   | Required | Type   | Comments                                    |
|----------------------------|----------|--------|---------------------------------------------|
| conntrackd_ignore_ip_list  | no       | Bool   | Enable contrackd if the variable is defined |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.conntrackd }
```
