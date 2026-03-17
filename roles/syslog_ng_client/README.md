# Syslog-ng client Role

This role configures syslog-ng to export logs from systemd-journald to a remote syslog-ng server.

## Requirements

No requirement.

## Role Variables

| Variable             | Required | Type        | Comments                                                           |
|----------------------|----------|-------------|--------------------------------------------------------------------|
| syslog_tls_ca        |  No      | String      | Syslog TLS public key                                              |
| syslog_tls_key       |  No      | String      | Syslog TLS private key                                             |
| syslog_tls_server_ca |  No      | String      | Syslog TLS CA                                                      |
| syslog_server_ip     |  No      | String      | IP address of the Syslog server to send logs                       |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.syslog-ng_client }
```
