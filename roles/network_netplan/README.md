# Network Netplan Role

This role configures the network via Netplan.

## Requirements

No requirement.

## Role Variables

| Variable               | Requiered | Type           | Comments                                                                               |
|------------------------|-----------|----------------|----------------------------------------------------------------------------------------|
| netplan_configurations | No        | List of string | List of netplan Ansible template files on the Ansible machine to be uploaded on target |

## Example Playbook

```yaml
- name: Network Netplan
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_netplan }
```
