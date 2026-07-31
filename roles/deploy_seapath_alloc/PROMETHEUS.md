# Configuring Prometheus for a SEAPATH deployment

This repository deploys the exporters (`deploy_prometheus_exporters`, the
Ceph mgr module via `cephadm`, the `seapath-alloc` textfile collector) and
ships ready-made Grafana dashboards
(`files/grafana-seapath-alloc.json`, `files/grafana-seapath-alloc-cluster.json`),
but it does not deploy Prometheus itself and cannot ship its scrape config:
Prometheus is normally shared across several SEAPATH sites and other
projects, so its configuration lives with the monitoring infrastructure, not
with a given cluster's inventory. This document describes the scrape
configuration a SEAPATH deployment needs on the Prometheus side, and why.

## Why this matters: labels are the join key

The single-node dashboard (`grafana-seapath-alloc.json`) only needs
Prometheus's built-in `instance` label (`address:port`), so it works with any
scrape config that reaches a node's `node_exporter` on port 9100, nothing
special to configure.

The cluster-wide dashboard (`grafana-seapath-alloc-cluster.json`) is a
different story: it correlates `seapath_alloc_*` metrics with
`ceph_health_status`, `ha_cluster_corosync_quorate`,
`ha_cluster_pacemaker_fail_count`, `libvirt_domain_info_state` and the
standard `node_exporter` metrics, all filtered and grouped by two custom
labels: `cluster` and `nodename`. Prometheus's own service-discovery labels
(`instance`, `job`) can't do this, because each service is scraped on a
different port under a different job name: `cluster`/`nodename` are the only
thing that ties a Ceph metric, a Pacemaker metric and a seapath-alloc metric
back to the same physical node. These two labels must therefore be attached
to every target at the service-discovery level, not derived later, which is
what the `file_sd_configs` plus static labels pattern below is for.

## Exporters and jobs

| Job name (example) | Exporter | Port | Deployed by | Runs on |
|---|---|---|---|---|
| `node` | `node_exporter` (also serves the `seapath-alloc` textfile metrics) | 9100 | `deploy_prometheus_exporters` | every host: `cluster_machines`, `hypervisors`, `VMs`, `standalone_machine` |
| `ceph` | Ceph mgr `prometheus` module | 9283 | `cephadm` (`cephadm_prometheus_exporter_enabled`, see [cephadm README](../cephadm/README.md#ceph-prometheus-exporter)) | hosts that run a mgr daemon, i.e. `cluster_machines` |
| `ha` | `ha_cluster_exporter` | 9664 | `deploy_prometheus_exporters` | `cluster_machines` |
| `seapath_custom_exporter` | `insatomcat-exporter` | 9184 | `deploy_prometheus_exporters` | `hypervisors` |
| `libvirt_exporter` | `prometheus-libvirt-exporter` | 9177 | `deploy_prometheus_exporters` | `hypervisors` |
| `podman_exporter` | `prometheus-podman-exporter` | 9882 | `deploy_prometheus_exporters` | `hypervisors` |

The `seapath-alloc` metrics (`seapath_alloc_*`) are not a separate job: they
are written as a Prometheus textfile
(`/var/lib/prometheus/node_exporter/seapath-alloc.prom`, see
[Textfile collector](README.md#textfile-collector)) and served by
`node_exporter` itself, so they ride on the `node` job.

## Required labels

| Label | Required for | Where it comes from |
|---|---|---|
| `cluster` | Cluster dashboard (`$cluster` template variable, used on almost every panel) | Static label on the target, set to the SEAPATH cluster name |
| `nodename` | Cluster dashboard (`$nodename` template variable, per-node panels) | Static label on the target, set to `inventory_hostname` |
| `project` | Not read by the bundled dashboards | Optional: useful to scope a multi-site/multi-project Prometheus (alerting rules, dashboard folders) |
| `seapath` | Scrape filtering only (see below) | Optional: only needed on a standalone machine (`standalone_machine` inventory group) |

`cluster` and `nodename` are mandatory for every `cluster_machines` /
`hypervisors` host if you want to use the cluster dashboard. A standalone
machine has no `cluster` group membership by definition, so it has no
meaningful `cluster` value; give it a one-node "cluster" name anyway (e.g.
the hostname) if you want it to show up in the cluster dashboard, or omit
`cluster`/`nodename` entirely and rely on the single-node dashboard instead.

## File-based service discovery

The simplest way to attach these labels is `file_sd_configs` with one YAML
file per project, matched by a glob. A project can mix a cluster with
standalone machines, e.g. a 3-node HA cluster plus a separate standalone
hypervisor:

```yaml
# /etc/prometheus/targets/<project>.yml
- targets: ["192.0.2.11"]
  labels: { project: siteA, cluster: siteA, nodename: siteA-node1 }
- targets: ["192.0.2.12"]
  labels: { project: siteA, cluster: siteA, nodename: siteA-node2 }
- targets: ["192.0.2.13"]
  labels: { project: siteA, cluster: siteA, nodename: siteA-node3 }
- targets: ["192.0.2.14"]
  labels: { project: siteA, nodename: siteA-admin, seapath: "true" }
```

The first three targets are cluster members: they get `cluster` for free.
The fourth is a standalone hypervisor in the same project: it has no
`cluster` label, so it needs `seapath: "true"` or it silently drops out of
the `libvirt_exporter`/`podman_exporter`/`seapath_custom_exporter` jobs (see
[Scrape filtering](#scrape-filtering) below). This is easy to miss:
forgetting the tag doesn't produce a "down" target, the host just never
becomes a target for those three jobs in the first place, so nothing
alerts on it.

Bare IPs work as targets because every job below rewrites `__address__` to
add its own port.

## Scrape jobs

Each exporter needs its own job, because each is scraped on a different
port. The pattern is the same for all of them:

```yaml
scrape_configs:
  - job_name: node
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
    relabel_configs:
      - source_labels: [__address__]
        regex: "(.+)"
        target_label: __address__
        replacement: "${1}:9100"

  - job_name: ceph
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
    metrics_path: /metrics
    relabel_configs:
      - source_labels: [cluster]
        regex: ".+"
        action: keep # only hosts that carry a cluster label run a mgr daemon
      - source_labels: [__address__]
        regex: "(.+)"
        target_label: __address__
        replacement: "${1}:9283"

  - job_name: ha
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
    metrics_path: /metrics
    relabel_configs:
      - source_labels: [cluster]
        regex: ".+"
        action: keep # ha_cluster_exporter only runs on cluster_machines
      - source_labels: [__address__]
        regex: "(.+)"
        target_label: __address__
        replacement: "${1}:9664"

  - job_name: seapath_custom_exporter
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
    metrics_path: /metrics
    relabel_configs:
      - source_labels: [cluster, seapath]
        separator: ";"
        regex: '.+;.*|.*;true'
        action: keep # hypervisors: cluster member, or explicitly tagged standalone
      - source_labels: [__address__]
        regex: "(.+)"
        target_label: __address__
        replacement: "${1}:9184"

  - job_name: libvirt_exporter
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
    metrics_path: /metrics
    relabel_configs:
      - source_labels: [cluster, seapath]
        separator: ";"
        regex: '.+;.*|.*;true'
        action: keep
      - source_labels: [__address__]
        regex: "(.+)"
        target_label: __address__
        replacement: "${1}:9177"

  - job_name: podman_exporter
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
    relabel_configs:
      - source_labels: [cluster, seapath]
        separator: ";"
        regex: '.+;.*|.*;true'
        action: keep
      - source_labels: [__address__]
        regex: "(.+)"
        target_label: __address__
        replacement: "${1}:9882"
```

### Scrape filtering

Every job except `node` needs a `keep` relabel rule, because
`file_sd_configs` is shared: without it, Prometheus would also try to scrape
`ceph`/`ha`/`libvirt_exporter`/etc. on VMs and non-SEAPATH hosts that don't
run those exporters, and (if the same Prometheus instance is shared with
other projects) on hosts that have nothing to do with SEAPATH at all.

- `ceph` and `ha` keep on `cluster` alone, because the mgr daemon and
  `ha_cluster_exporter` both run on the whole `cluster_machines` group
  (see the [exporter table](#exporters-and-jobs)).
- `seapath_custom_exporter`, `libvirt_exporter` and `podman_exporter` keep on
  `cluster` or `seapath: "true"`, because those three exporters run on
  `hypervisors`, not `cluster_machines`. In the common case where every
  cluster node is also a hypervisor (the default 3-hypervisor topology in
  `inventories/examples/seapath-cluster.yaml`), `cluster` alone already
  selects the right hosts. The `seapath: "true"` fallback exists for
  standalone machines, which carry no `cluster` label; without it they would
  never be scraped by these three jobs.

**Caveat, 2-hypervisor + 1-observer clusters:** an observer is in
`cluster_machines` (so it correctly gets `cluster`/`ha` scraping) but not in
`hypervisors`, so it never runs `podman-exporter` / `libvirt-exporter` /
`insatomcat-exporter`. The `keep` rule above cannot tell an observer apart
from a hypervisor (both simply carry `cluster: <name>`), so those three jobs
will show a permanently down target for the observer. This is harmless
(Prometheus just reports the target as down) but worth silencing in
alerting rules if you use the 2+1 observer topology.

## Combining bare IPs across jobs

If you need a stable, port-independent identifier for a host (for example to
link panels or exemplars across jobs that use different ports), capture the
bare address into its own label before the port is appended, since after
that point `__address__`/`instance` differs per job:

```yaml
relabel_configs:
  - source_labels: [__address__]
    target_label: host
  - source_labels: [__address__]
    regex: "(.+)"
    target_label: __address__
    replacement: "${1}:9100"
```

Neither of the bundled dashboards needs this (the cluster dashboard keys off
`cluster`/`nodename`, the single-node one off `instance`), so treat it as
optional convenience, not a requirement.
