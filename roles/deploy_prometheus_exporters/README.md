# Deploy Prometheus exporters Role

This role deploys Prometheus exporters as Podman quadlet container units under
`/etc/containers/systemd/`, then enables and starts the corresponding systemd
services.

The exporters are bound to the administration IP address, which defaults to the
standard SEAPATH `ip_addr` inventory variable.

## Requirements

- Podman with quadlet/systemd container support
- Yocto is not supported yet; the role is skipped when `seapath_distro` is
  `Yocto` until compatibility is added
- `podman.socket` for the podman exporter (API socket at `/run/podman/podman.sock`)
- Libvirt socket access for libvirt and insatomcat exporters (`libvirtd.service` on
  Debian, `virtqemud.service` on Oracle Linux)
- Pacemaker/Corosync tools on the host for the HA cluster exporter
- `seapath_distro` should be set, typically by calling `detect_seapath_distro`
  before this role

## Role Variables

| Variable | Required | Type | Default | Comments |
|---|---|---|---|---|
| `deploy_prometheus_exporters_enabled` | No | Boolean | `true` | Set to `false` on Yocto until Yocto support is added |
| `deploy_prometheus_exporters_exporters` | No | List | see below | Exporters to deploy on the host |
| `deploy_prometheus_exporters_listen_address` | No | String | `"{{ ip_addr \| default(ansible_host) }}"` | IP address exporters listen on |
| `deploy_prometheus_exporters_images` | No | Dict | `{}` | Container images keyed by exporter name |
| `deploy_prometheus_exporters_node_exporter_image` | No | String | see defaults | Node exporter container image |
| `deploy_prometheus_exporters_podman_exporter_image` | No | String | see defaults | Podman exporter container image |
| `deploy_prometheus_exporters_libvirt_exporter_image` | No | String | see defaults | Libvirt exporter container image |
| `deploy_prometheus_exporters_insatomcat_exporter_image` | No | String | see defaults | Insatomcat exporter container image |
| `deploy_prometheus_exporters_ha_cluster_exporter_image` | No | String | see defaults | HA cluster exporter container image |
| `deploy_prometheus_exporters_manage_services` | No | Boolean | `true` | Enable and start systemd units |
| `deploy_prometheus_exporters_register_essential_services` | No | Boolean | `true` | Publish deployed services for cukinia tests |
| `deploy_prometheus_exporters_libvirt_exporter_socket` | No | String | see vars | Host libvirt socket mounted in libvirt exporter |
| `deploy_prometheus_exporters_insatomcat_libvirt_socket` | No | String | see vars | Host libvirt socket mounted in insatomcat exporter |
| `deploy_prometheus_exporters_insatomcat_qemu_dir` | No | String | `/var/run/libvirt/qemu` | Host QEMU runtime dir for insatomcat exporter |
| `deploy_prometheus_exporters_libvirt_systemd_unit` | No | String | see vars | Libvirt systemd unit to order exporter startup after |

Default upstream images are defined in `vars/main.yml` under
`deploy_prometheus_exporters_default_images`. Libvirt socket paths and the
related systemd unit are defined in `vars/<seapath_distro>.yml`. Override them
per exporter with
either `deploy_prometheus_exporters_images` or the dedicated `*_image`
variables.

### Supported exporters

| Name | Port | Hosts |
|---|---|---|
| `node-exporter` | 9100 | all |
| `podman-exporter` | 9882 | hypervisors |
| `libvirt-exporter` | 9177 | hypervisors |
| `insatomcat-exporter` | 9184 | hypervisors |
| `ha_cluster_exporter` | 9664 | cluster machines |

### Default exporter selection

When `deploy_prometheus_exporters_exporters` is not overridden, exporters are
added from the inventory groups the host belongs to:

| Exporter | Added when the host is in |
|---|---|
| `node-exporter` | always |
| `ha_cluster_exporter` | `cluster_machines` |
| `podman-exporter`, `libvirt-exporter`, `insatomcat-exporter` | `hypervisors` |

Examples:

| Host | Groups | Result |
|---|---|---|
| Cluster hypervisor | `cluster_machines`, `hypervisors` | all exporters |
| Observer | `cluster_machines` only | node + ha cluster |
| Standalone hypervisor | `hypervisors` | node + podman + libvirt + insatomcat |
| VM | `VMs` | node only |

The mapping is defined in `vars/main.yml` as
`deploy_prometheus_exporters_group_exporters`.

### Libvirt socket paths per flavor

| Flavor | Libvirt exporter socket | insatomcat libvirt socket | systemd unit |
|---|---|---|---|
| Debian, CentOS, SLES | `/var/run/libvirt/libvirt-sock-ro` | `/var/run/libvirt/libvirt-sock` | `libvirtd.service` |
| Oracle Linux | `/run/libvirt/virtqemud-sock` | `/run/libvirt/virtqemud-sock` | `virtqemud.service` |

## Example Playbook

```yaml
- name: Deploy prometheus exporters
  hosts:
    - cluster_machines
    - standalone_machine
    - VMs
  become: true
  roles:
    - detect_seapath_distro
    - deploy_prometheus_exporters
```

The role derives the exporter list from the inventory groups. Override it
explicitly when needed:

```yaml
deploy_prometheus_exporters_exporters:
  - node-exporter
```

## Offline or internal registry

When nodes cannot reach public registries, mirror the exporter images on a
local registry and override the image references from the inventory.

Override all images at once:

```yaml
# group_vars/all.yml
deploy_prometheus_exporters_images:
  node-exporter: registry.local/seapath/node-exporter:1.8.2
  podman-exporter: registry.local/seapath/prometheus-podman-exporter:1.14.0
  libvirt-exporter: registry.local/seapath/prometheus-libvirt-exporter:2.3.1
  insatomcat-exporter: registry.local/seapath/insatomcat-exporter:1.0.0
  ha_cluster_exporter: registry.local/seapath/ha-cluster-exporter:0.0.1
```

Override a single exporter:

```yaml
deploy_prometheus_exporters_node_exporter_image: registry.local/seapath/node-exporter:1.8.2
```

Podman pulls the image when systemd starts each quadlet service. In offline
environments, point the image URLs to a reachable internal registry where the
images have been mirrored.

When cukinia tests are used, deployed exporter services are written to
`/etc/cukinia/extra-essential-services.d/deploy_prometheus_exporters`.
This drop-in is read at test runtime, so it still applies when cukinia tests
are deployed or executed in a separate playbook run.
