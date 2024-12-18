# centos Role

This role apply the basic SEAPATH prerequisites for any CentOS machine

## Requirements

no requirement.

## Role Variables

| Variable             | Type        | Comments                                                           |
|----------------------|-------------|--------------------------------------------------------------------|
| syslog_tls_ca        | String      | Syslog TLS public key                                              |
| syslog_tls_key       | String      | Syslog TLS private key                                             |
| syslog_tls_server_ca | String      | Syslog TLS CA                                                      |
| admin_user           | String      | User to use for administration                                     |
| admin_passwd         | String      | Optional user password                                             |
| admin_ssh_keys       | String list | List of SSH public keys used to connect to the administration user |
| grub_append          | String list | List of extra kernel parameters                                    |
| syslog_server_ip     | String      | IP address of the Syslog server to send logs                       |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.centos }
```
