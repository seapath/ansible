# Syslog-ng client Role

This role configures syslog-ng to export logs from systemd-journald to a remote syslog-ng server.

## Requirements

Syslog-ng package must be installed on the host and syslog-ng.service must exists.

To enable TLS encryption, all three `syslog_tls_ca`, `syslog_tls_key` and `syslog_tls_server_ca`
variables must be provided.
If not, TLS encryption is deactivated.

## Role Variables

| Variable             | Required | Type        | Default | Comments                                                           |
|----------------------|----------|-------------|---------|--------------------------------------------------------------------|
| syslog_conf_template |  No      | String      | Config template provided by the role | Local path to the syslog-ng configuration template.|
| syslog_tls_ca        |  No      | String      |         | Syslog TLS public key                                              |
| syslog_tls_key       |  No      | String      |         | Syslog TLS private key                                             |
| syslog_tls_server_ca |  No      | String      |         | Syslog TLS CA                                                      |

## Role's configuration template variables

| Variable             | Required | Type        | Default | Comments                                                           |
|----------------------|----------|-------------|---------|--------------------------------------------------------------------|
| syslog_server_ip     |  No      | String      |         | IP address of the Syslog server to send logs                       |
| syslog_tls_port      |  No      | Int         | 6514    | Remote server TLS port. Only when TLS encryption is enabled        |
| syslog_tcp_port      |  No      | Int         | 601     | Remote server TCP port. Only when TLS encryption is disabled       |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.syslog-ng_client }
```
