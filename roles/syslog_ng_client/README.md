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

## Configuration version

The `@version` line of `syslog-ng.conf` is read from the installed syslog-ng
(`syslog-ng --version`), so a machine running 4.8 gets `@version: 4.8` instead
of the 3.38 the template used to hardcode, and syslog-ng stops warning about a
configuration older than itself at every start.

A declared version below the installed one runs the configuration in
compatibility mode, and a version above it is refused outright, which is why
the role never guesses: when reading the installed version fails it falls back
to `syslog_config_version_fallback`. Set `syslog_config_version` to pin the
declared version and skip the detection entirely.

| Variable                       | Required | Type   | Default  | Comments                                          |
|--------------------------------|----------|--------|----------|----------------------------------------------------|
| syslog_config_version          |  No      | String | detected | Pin the declared version, skipping the detection   |
| syslog_config_version_fallback |  No      | String | `3.38`   | Used only when the detection fails                 |

## TLS policy

When TLS is enabled the destination restricts the handshake to TLS 1.2 and
newer with AEAD cipher suites, and verifies the server against
`syslog_tls_server_ca`. `cipher-suite` only covers TLS 1.2 and below; TLS 1.3
negotiates its own suites, which syslog-ng exposes from 4.0 onwards through
`openssl-conf-cmds()`.

Verifying the CA accepts any certificate that CA signed. On a CA shared with
other services, pin the collector itself with `syslog_tls_trusted_dn` (a list
of distinguished name patterns) or `syslog_tls_trusted_keys` (a list of
`SHA1:` certificate fingerprints). Both are left out of the configuration
when undefined.

| Variable                 | Required | Type   | Default | Comments                                                      |
|--------------------------|----------|--------|---------|----------------------------------------------------------------|
| syslog_tls_peer_verify   |  No      | String | `required-trusted` | syslog-ng `peer-verify()` value                     |
| syslog_tls_ssl_options   |  No      | List   | TLS 1.2+ | syslog-ng `ssl-options()` values; empty to omit the option    |
| syslog_tls_cipher_suite  |  No      | String | ECDHE AEAD suites | OpenSSL cipher list; empty to omit the option        |
| syslog_tls_trusted_dn    |  No      | List   |         | Accept the server only if its DN matches one of these patterns |
| syslog_tls_trusted_keys  |  No      | List   |         | Accept the server only if its fingerprint is one of these      |

## Disk buffer

The remote destination buffers on disk, so that logs produced while the
administration network is down are sent once it comes back instead of being
dropped. The buffer lives in `syslog_disk_buffer_dir`, which the role creates
and which must stay inside the `ReadWritePaths` of the hardened syslog-ng unit
(`configure_hardening` allows `/var/lib/syslog-ng`).

`reliable(no)` is the default: messages queue in memory first and spill to
disk under pressure, so a crash can lose what was still in the front queue. Set
`syslog_disk_buffer_reliable` to `true` to write every message to disk before
acknowledging it, at the cost of one I/O per message.

| Variable                       | Required | Type    | Default                        | Comments                                                        |
|--------------------------------|----------|---------|--------------------------------|-----------------------------------------------------------------|
| syslog_disk_buffer             |  No      | Boolean | `true`                         | Buffer outgoing messages on disk                                |
| syslog_disk_buffer_dir         |  No      | String  | `/var/lib/syslog-ng/disk-buffer` | Directory holding the buffer files                            |
| syslog_disk_buffer_size        |  No      | Int     | `134217728`                    | Maximum buffer size in bytes (syslog-ng minimum is `1048576`)   |
| syslog_disk_buffer_reliable    |  No      | Boolean | `false`                        | Write every message to disk before acknowledging it             |
| syslog_disk_buffer_mem_length  |  No      | Int     | `10000`                        | Front queue in messages, used when `reliable` is `false`        |
| syslog_disk_buffer_mem_size    |  No      | Int     | `1048576`                      | Front queue in bytes, used when `reliable` is `true`            |

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
