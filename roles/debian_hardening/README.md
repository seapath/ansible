# Debian Hardening Role

This role apply the hardening SEAPATH configurations.

## Requirements

No requirement.

## Role Variables

| Variable        | Type   | Comments                        |
|-----------------|--------|---------------------------------|
| admin_user      | String | Administrator Unix username     |
| grub_password   | String | Password to access grub console |
| ip_addr         | String | IP address for administration   |
| cluster_ip_addr | String | Cluster IP address              |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_hardening }
```
