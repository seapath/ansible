# Conntrackd Role

This role configure the conntrackd feature

## Requirements

No requirement.

## Role Variables

- conntrackd_ignore_ip_list

| Variable                   | Required | Type   | Default | Comments                                                |
|----------------------------|----------|--------|---------|---------------------------------------------------------|
| conntrackd_ignore_ip_list  | no       | Bool   | none    | Enable contrackd if the variable is defined             |
| conntrackd_interface       | no       | String | team0   | Set the network interface on which conntrackd will work |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.conntrackd }
```
