# Hardening Role

This role apply hardening SEAPATH configurations.

Note that this role isn't necessary for SEAPATH Yocto as hardening is done at build time.

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
    - { role: seapath_ansible.configure_hardening }
```
