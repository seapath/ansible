# cephadm Role

This role provisions the Ceph cluster using cephadm. Installation of the cephadm binary, prerequisites (users, groups, sudo), image pulling, and registry setup is handled by the `cephadm_install` role.

## Requirements

The `cephadm_install` role must have been applied to `cluster_machines` before this role runs.

## Role Variables

| Variable                          | Required | Type    | Default      | Comments                                                                              |
|-----------------------------------|----------|---------|--------------|---------------------------------------------------------------------------------------|
| seapath_distro                    | No       | String  | Not set      | SEAPATH distribution                                                                  |
| cephadm_release                   | No       | String  | "20.2.0"     | Version of the ceph container image                                                   |
| cephadm_spec_path                 | No       | String  | spec.yaml.j2 | Path to the spec file of cephadm. Use it to override the default config               |
| cephadm_network                   | Yes      | String  |              | Ceph network (e.g. "192.168.55.0/24")                                                 |
| cephadm_prometheus_exporter_enabled | No     | Boolean | `true`       | Enable the built-in Ceph mgr prometheus module after the cluster is healthy           |
| cephadm_prometheus_listen_address   | No     | String  | see defaults | Administration IP the mgr prometheus exporter binds to on each host. Defaults to `ip_addr`, same as `deploy_prometheus_exporters_listen_address`. Override per host in inventory if needed. |

Note that for each node you want in the cluster, those host vars need to be defined:

| Variable               | Required | Type   | Comments                                                                              |
|------------------------|----------|--------|---------------------------------------------------------------------------------------|
| hostname               | Yes      | String | The hostname of the machine. Can be fallback to "inventory_hostname" in the inventory |
| cluster_ip_addr        | Yes      | String | IP address of the machine on the cluster network                                      |

More information about ceph networks on [ceph documentation](https://docs.ceph.com/en/latest/rados/configuration/network-config-ref/).

## Ceph prometheus exporter

When `cephadm_prometheus_exporter_enabled` is `true` (default), the role enables the
built-in Ceph mgr prometheus module once the cluster reaches `HEALTH_OK`:

- `ceph mgr module enable prometheus`
- `ceph config set mgr mgr/prometheus/exclude_perf_counters false`
- `ceph config set mgr.<hostname>.<id> mgr/prometheus/server_addr <admin-ip>` on each mgr
  daemon, using `cephadm_prometheus_listen_address` (defaults to `ip_addr`, same as
  `deploy_prometheus_exporters_listen_address`)

The role discovers mgr daemon names with `ceph orch ps --daemon-type=mgr`, matches each
daemon to an inventory host via the `hostname` host variable, and sets the listen address
to that host's administration IP.

This exporter is part of the Ceph cluster (mgr daemon, port 9283). It is separate
from the host-level exporters deployed by the `deploy_prometheus_exporters` role.

The cluster bootstrap uses `--skip-monitoring-stack`, so Ceph does not deploy its own
Prometheus server. Configure an external Prometheus scrape job for the mgr endpoints
after this role runs.

Set `cephadm_prometheus_exporter_enabled: false` to skip this step.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cephadm }
```
