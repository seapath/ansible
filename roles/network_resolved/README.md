# Network Resolved Role

This role configures the DNS with resolved.

## Requirements

No requirement.

## Role Variables

| Variable    | Requiered | Type           | Comments        |
|-------------|-----------|----------------|-----------------|
| dns_servers | No        | List of string | DNS server list |

## Example Playbook

```yaml
- name: Network Resolved
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_resolved }
```
