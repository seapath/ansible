# Hardening Role

This role apply hardening SEAPATH configurations.

Note that this role isn't necessary for SEAPATH Yocto as hardening is done at build time.

## Requirements

No requirement.

## Role Variables

| Variable        | Required | Type   | Default | Comments                        |
|-----------------|----------|--------|---------|---------------------------------|
| admin_user      | Yes      | String |         | Administrator Unix username     |
| grub_password   | Yes      | String |         | Password to access grub console |
| ip_addr         | Yes      | String |         | IP address for administration   |
| cluster_ip_addr | No       | String |         | Cluster IP address              |
| configure_hardening_ssh_service | Yes | String |  | Name of SSH systemd service |
| configure_hardening_login_defs_file | No | String | /etc/login.defs | The login.defs file to configure |
| configure_hardening_etc_securetty_group | No | String | root | The group of the /etc/securetty file |
| configure_hardening_grub_update_command | Yes | String | | Command to be run to update GRUB after configuration modification |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_hardening }
```
