# Deploy Prometheus exporters Role

This role deploys Prometheus exporters as Podman quadlet container units under
`/etc/containers/systemd/`, then starts the corresponding systemd services.
Activation at boot comes from the `[Install]` section of the quadlet units.

The exporters are bound to the administration IP address, which defaults to the
standard SEAPATH `ip_addr` inventory variable. With the per-node metrics proxy
deployed (`deploy_metrics_proxy_enabled`, see the
[deploy_metrics_proxy role](../deploy_metrics_proxy/README.md)) they bind to
the loopback instead, and that proxy becomes the single endpoint this node
exposes.

## Requirements

- Podman with quadlet/systemd container support
- Yocto and SLES are not supported yet; the role is skipped when
  `seapath_distro` is `Yocto` or `SLES` until compatibility is added
- `podman.socket` for the podman exporter (API socket at `/run/podman/podman.sock`)
- Libvirt socket access for libvirt and SEAPATH exporters (`libvirtd.service` on
  Debian, `virtqemud.service` on Oracle Linux)
- Pacemaker/Corosync tools on the host for the HA cluster exporter
- The smartctl exporter runs privileged: it sends SMART commands to the disks
  of the host
- `seapath_distro` should be set, typically by calling `detect_seapath_distro`
  before this role

## Role Variables

| Variable | Required | Type | Default | Comments |
|---|---|---|---|---|
| `deploy_prometheus_exporters_enabled` | No | Boolean | `true` | Set to `false` on Yocto and SLES until support is added |
| `deploy_prometheus_exporters_exporters` | No | List | see below | Exporters to deploy on the host |
| `deploy_prometheus_exporters_listen_address` | No | String | `ip_addr`, or `127.0.0.1` with the metrics proxy | IP address exporters listen on |
| `deploy_prometheus_exporters_images` | No | Dict | `{}` | Container images keyed by exporter name |
| `deploy_prometheus_exporters_node_exporter_image` | No | String | see defaults | Node exporter container image |
| `deploy_prometheus_exporters_podman_exporter_image` | No | String | see defaults | Podman exporter container image |
| `deploy_prometheus_exporters_libvirt_exporter_image` | No | String | see defaults | Libvirt exporter container image |
| `deploy_prometheus_exporters_seapath_exporter_image` | No | String | see defaults | SEAPATH exporter container image |
| `deploy_prometheus_exporters_ha_cluster_exporter_image` | No | String | see defaults | HA cluster exporter container image |
| `deploy_prometheus_exporters_smartctl_exporter_image` | No | String | see defaults | smartctl exporter container image |
| `deploy_prometheus_exporters_smartctl_interval` | No | String | `300s` | How often the smartctl exporter asks the disks, see below |
| `deploy_prometheus_exporters_manage_services` | No | Boolean | `true` | Start systemd units and restart them on unit file changes |
| `deploy_prometheus_exporters_lvm_enabled` | No | Boolean | `true` | Write the LVM metrics to the node exporter textfile collector, see below |
| `deploy_prometheus_exporters_register_essential_services` | No | Boolean | `true` | Publish deployed services for cukinia tests |
| `deploy_prometheus_exporters_libvirt_exporter_socket` | No | String | see vars | Host libvirt socket mounted in libvirt exporter |
| `deploy_prometheus_exporters_seapath_exporter_libvirt_socket` | No | String | see vars | Host libvirt socket mounted in SEAPATH exporter |
| `deploy_prometheus_exporters_seapath_exporter_qemu_dir` | No | String | `/var/run/libvirt/qemu` | Host QEMU runtime dir for SEAPATH exporter |
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
| `seapath-exporter` | 9184 | hypervisors |
| `ha_cluster_exporter` | 9664 | cluster machines |
| `smartctl-exporter` | 9633 | cluster machines and hypervisors |

### Default exporter selection

When `deploy_prometheus_exporters_exporters` is not overridden, exporters are
added from the inventory groups the host belongs to:

| Exporter | Added when the host is in |
|---|---|
| `node-exporter` | always |
| `ha_cluster_exporter` | `cluster_machines` |
| `podman-exporter`, `libvirt-exporter`, `seapath-exporter` | `hypervisors` |
| `smartctl-exporter` | `cluster_machines` or `hypervisors` |

Examples:

| Host | Groups | Result |
|---|---|---|
| Cluster hypervisor | `cluster_machines`, `hypervisors` | all exporters |
| Observer | `cluster_machines` only | node + ha cluster + smartctl |
| Standalone hypervisor | `hypervisors` | node + podman + libvirt + seapath + smartctl |
| VM | `VMs` | node only |

The mapping is defined in `vars/main.yml` as
`deploy_prometheus_exporters_group_exporters`.

### Libvirt socket paths per flavor

| Flavor | Libvirt exporter socket | SEAPATH exporter libvirt socket | systemd unit |
|---|---|---|---|
| Debian, CentOS, SLES | `/var/run/libvirt/libvirt-sock-ro` | `/var/run/libvirt/libvirt-sock` | `libvirtd.service` |
| Oracle Linux | `/run/libvirt/virtqemud-sock` | `/run/libvirt/virtqemud-sock` | `virtqemud.service` |

## Disk health

node_exporter says how full and how busy a disk is, and nothing of its health.
The [smartctl exporter](https://github.com/prometheus-community/smartctl_exporter)
runs `smartctl` on every disk it finds, SATA, SAS and NVMe, and serves what
they answer. It is deployed on the physical machines, the ones of a cluster
and the hypervisors, and on no VM: a virtual disk has no SMART data.

| Metric | Labels | Meaning |
|---|---|---|
| `smartctl_device` | `device`, `model_name`, `serial_number`, `firmware_version`, `interface`, `protocol` | Always 1: what the disk is |
| `smartctl_device_smart_status` | `device` | 1 when the disk says it is healthy, 0 when it predicts its failure |
| `smartctl_device_smartctl_exit_status` | `device` | Exit status of `smartctl`, a bit mask: 0 when the disk answered every command |
| `smartctl_device_temperature` | `device`, `temperature_type` | Temperature in Celsius |
| `smartctl_device_power_on_seconds`, `smartctl_device_power_cycle_count` | `device` | How long the disk has run, and how many times it was powered |
| `smartctl_device_capacity_bytes` | `device` | Size of the disk |
| `smartctl_device_attribute` | `device`, `attribute_id`, `attribute_name`, `attribute_value_type` | Each SMART attribute of an ATA disk: `raw`, `value`, `worst` and `thresh` |
| `smartctl_device_percentage_used`, `smartctl_device_available_spare`, `smartctl_device_media_errors`, `smartctl_device_critical_warning` | `device` | Wear, spare blocks, media errors and warnings of an NVMe disk |
| `smartctl_devices` | | Number of disks found |

The attributes of an ATA disk are the vendor's: their names and the meaning
of their raw value change from one model to another, and `value` against
`thresh` is what compares across disks. The wear of a SATA SSD is one of
them (`Media_Wearout_Indicator`, `Wear_Leveling_Count` or
`Percent_Lifetime_Remain`, depending on the vendor).

The disks are asked every `deploy_prometheus_exporters_smartctl_interval`,
five minutes unless the inventory says otherwise, and a scrape is answered
from what they said then: scraping more often sends them no more commands.

Some alerts worth setting:

- `smartctl_device_smart_status == 0`: the disk predicts its own failure.
- `smartctl_device_attribute{attribute_name="Reallocated_Sector_Ct",attribute_value_type="raw"} > 0`
  and growing, or `smartctl_device_media_errors > 0` on NVMe.
- `smartctl_devices` lower than it was: a disk is no longer seen.

A disk behind a hardware RAID controller is seen only when the controller
passes SMART commands through.

## LVM metrics

node_exporter reports the file systems mounted on logical volumes and the I/O
of their device-mapper devices, but nothing of the LVM layer itself. On the
machines that run the node exporter and have LVM installed (`/usr/sbin/lvm`),
the role adds a `seapath-lvm-textfile.timer`. Every minute it runs
`/usr/local/sbin/seapath-lvm-textfile`, which reads `vgs`, `pvs` and `lvs` and
writes `/var/lib/prometheus/node_exporter/seapath_lvm.prom`, served by the node
exporter on its next scrape.

| Metric | Labels | Meaning |
|---|---|---|
| `seapath_lvm_vg_size_bytes`, `seapath_lvm_vg_free_bytes` | `vg` | Size and unallocated space of the volume group |
| `seapath_lvm_vg_pv_count`, `seapath_lvm_vg_missing_pv_count` | `vg` | Physical volumes in the group, and those that cannot be found |
| `seapath_lvm_vg_lv_count`, `seapath_lvm_vg_snapshot_count` | `vg` | Logical volumes and snapshots in the group |
| `seapath_lvm_pv_size_bytes`, `seapath_lvm_pv_free_bytes`, `seapath_lvm_pv_missing` | `pv`, `vg` | Size, free space and presence of each physical volume. `vg` is empty for a PV in no group |
| `seapath_lvm_lv_info` | `vg`, `lv`, `segtype`, `origin`, `pool` | Always 1: the type of the LV, the origin of a snapshot, the pool of a thin volume |
| `seapath_lvm_lv_size_bytes` | `vg`, `lv` | Size of the logical volume |
| `seapath_lvm_lv_active` | `vg`, `lv` | 1 when the LV is active on this node |
| `seapath_lvm_lv_data_ratio` | `vg`, `lv` | Used share, 0 to 1, of a snapshot, thin pool or thin volume |
| `seapath_lvm_lv_metadata_ratio` | `vg`, `lv` | Used share of the metadata of a thin or cache pool |
| `seapath_lvm_lv_healthy` | `vg`, `lv` | 0 when `lv_health_status` reports a problem; `lvs -o +lv_health_status` tells which |
| `seapath_lvm_lv_merging` | `vg`, `lv` | 1 while a snapshot is being merged back into its origin |
| `seapath_lvm_lv_snapshot_invalid` | `vg`, `lv` | 1 when a snapshot has overflowed and can no longer be used |
| `seapath_lvm_collect_success` | | 0 when the last run failed |
| `seapath_lvm_collect_duration_seconds` | | Time the last run took |

A metric that does not apply to an LV, such as the fill ratio of a linear
volume, is left out rather than written as 0.

Each LVM command is given 15 seconds. A run that fails or times out writes
`seapath_lvm_collect_success 0` and nothing else, so that the figures of an
earlier run are never served as current ones.

Some alerts worth setting, given how SEAPATH uses LVM:

- `seapath_lvm_lv_data_ratio{lv="root-snap"} > 0.8`: the snapshot taken by
  `seapath_update_debian.yaml` is filling up. At 100 % it is invalidated and
  the update can no longer be rolled back.
- `seapath_lvm_lv_info{lv="root-snap"}` present for more than a few days: an
  update was never finished or cleaned up, and the next one will refuse to
  run.
- `seapath_lvm_vg_free_bytes{vg="vg1"}` below `snapshot_min_size_gib` (2 GiB
  by default): the next Debian update will refuse to run.
- `seapath_lvm_lv_healthy == 0`, `seapath_lvm_vg_missing_pv_count > 0` or
  `seapath_lvm_collect_success == 0`.

Set `deploy_prometheus_exporters_lvm_enabled: false` to leave them out; the
role then removes the timer, the script and the metrics file.

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
  seapath-exporter: registry.local/seapath/seapath-exporter:1.0.0
  ha_cluster_exporter: registry.local/seapath/ha-cluster-exporter:0.0.1
  smartctl-exporter: registry.local/seapath/smartctl-exporter:v0.14.0
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
