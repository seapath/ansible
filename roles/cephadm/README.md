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
| ceph_osd_disks         | No       | List   | Paths of the block devices to give to Ceph on this node, one OSD per entry. Whole disks (recommended, `/dev/disk/by-path/...`) or pre-existing logical volumes |
| ceph_osd_disk          | No       | String | Shorthand for a one-element `ceph_osd_disks` list                                     |

A node with a non-empty `ceph_osd_disks` list carries OSDs; a node without it
only provides monitor/manager services. To add an OSD to a node (new disk or
new node), add its path to `ceph_osd_disks` and re-run the playbook.

More information about ceph networks on [ceph documentation](https://docs.ceph.com/en/latest/rados/configuration/network-config-ref/).

## OSD volume handling

Before adding OSDs, the role decides for each OSD volume whether it must be
wiped, using a single rule: **a volume is kept untouched if and only if it
hosts an OSD claimed by the running cluster** (the OSD uuid stored in the LVM
tags written by ceph-volume is registered in the cluster OSD map). Any other
volume listed for Ceph is zapped and enrolled as a new OSD.

Consequences:

- Re-running the playbook on a live cluster never touches existing OSDs.
- Reinstalling a cluster from scratch (new fsid, empty OSD map) automatically
  wipes and re-enrolls volumes containing data from the previous installation.
- A replaced machine has its volume re-enrolled without manual cleanup.

Logical volumes listed in `ceph_osd_disks` are wiped in place (the volume
layout belongs to the user); whole disks and partitions are destroyed so that
ceph-volume can create its own LVM layer on them.

## Custom OSD layouts

For layouts the default spec cannot describe (separate WAL/DB devices,
encryption, size or model filters...), provide your own service specification
with `cephadm_spec_path`. The role then still wipes the devices listed in
`ceph_osd_disks` (possibly none) before applying your spec, and nothing else:
devices referenced only by a custom spec must be prepared by the user, as the
playbook never wipes a device that is not declared in the inventory.

## Migrating from the legacy vg_ceph/lv_ceph layout

Clusters deployed by older versions of these playbooks host their OSDs on a
`vg_ceph/lv_ceph` volume and use `osdN` service ids. Re-running the playbook
on such a cluster is safe: the volumes are claimed by the cluster and left
untouched, but the newly applied spec declares per-hostname OSD services next
to the legacy `osd.osdN` ones in `ceph orch ls`. To fully migrate a node to
the whole-disk layout, remove its OSD with `ceph orch osd rm`, remove the LVM
layout of the disk, and re-run the playbook with the disk in
`ceph_osd_disks`.

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
