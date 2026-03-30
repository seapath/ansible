# Podman Registry Mirror Role

Configure podman registry mirroring for container registries.
This role sets up mirroring for docker.io and quay.io to a specified mirror URL, with optional TLS support.

## Requirements

No requirements.

## Role Variables

| Variable                            | Required | Type    | Default | Comments                                                                                            |
|-------------------------------------|----------|---------|---------|-----------------------------------------------------------------------------------------------------|
| podman_registry_mirror_url          | Yes      | string  |         | Mirror URL (e.g. "192.168.1.10:5000").                                                              |
| podman_registry_mirror_ca_cert_path | No*      | string  |         | Path to the registry CA certificate file on the Ansible control node. Required when TLS is enabled. |
| podman_registry_mirror_tls_enabled  | No       | boolean | false   | Enable TLS when communicating with the mirror registry.                                             |

## Example Playbook

```yaml
- hosts: cluster_machines
  vars:
    podman_registry_mirror_url: "192.168.1.10:5000"
    podman_registry_mirror_ca_cert_path: "/tmp/registry-ca.crt"
    podman_registry_mirror_tls_enabled: true
  roles:
    - { role: podman_registry_mirror }
```
