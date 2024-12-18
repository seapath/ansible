# Debian Hardening Role

This role apply the hardening SEAPATH configurations.

## Requirements

No requirement.

## Role Variables

| Variable        | Required | Type   | Comments                        |
|-----------------|----------|--------|---------------------------------|
| admin_user      | Yes      | String | Administrator Unix username     |
| grub_password   | Yes      | String | Password to access grub console |
| ip_addr         | Yes      | String | IP address for administration   |
| cluster_ip_addr | No       | String | Cluster IP address              |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_hardening }
```
