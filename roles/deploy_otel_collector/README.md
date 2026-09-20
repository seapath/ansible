# Deploy OpenTelemetry collector Role

This role deploys one OpenTelemetry collector per node, as a Podman quadlet
container unit under `/etc/containers/systemd/`, in front of the Prometheus
exporters `deploy_prometheus_exporters` and `cephadm` deploy.

The collector scrapes those exporters on `127.0.0.1` and serves the aggregate
on a single TLS endpoint. Turning it on with `deploy_otel_collector_enabled`
also moves the exporters to the loopback: both
`deploy_prometheus_exporters_listen_address` and
`cephadm_prometheus_listen_address` read that variable to decide where they
bind.

## What this is for

A hypervisor of a cluster exposes six HTTP endpoints on its administration
address, all in the clear and unauthenticated: node-exporter (9100),
libvirt-exporter (9177), insatomcat-exporter (9184), podman-exporter (9882),
ha_cluster_exporter (9664) and the Ceph mgr `prometheus` module (9283). Among
other things, 9100 serves the `seapath_rt_*` textfile block: the tuned profile,
the kernel command line, the RT throttling window, the hugepages per NUMA node,
SMT, THP, the interrupt affinities reaching the isolated cores. That is the
real-time tuning of the machine, readable by anyone who reaches the
administration network.

Configuring TLS on each exporter is the alternative, and it does not work:
node-exporter and podman-exporter support `--web.config.file` through the
Prometheus exporter-toolkit, the others support it unevenly or not at all, and
none of them is configured for it here. One collector in front means one
certificate to deploy and rotate, one TLS policy to audit, and one port.

**The model stays pull.** The central Prometheus keeps scraping, one target per
node instead of six, so a node that dies is still a target that goes down
immediately. Switching to an outbound push is a separate decision, which this
role does not take.

## Requirements

- Podman with quadlet/systemd container support
- `openssl` on the node, when it signs its own certificate
- `deploy_prometheus_exporters` deployed on the same host, normally in the same
  play (`playbooks/seapath_setup_prometheus_exporters.yaml`)

## Certificates

Nothing has to be provided: without `deploy_otel_collector_tls_cert` and
`deploy_otel_collector_tls_key`, the node signs its own certificate, valid ten
years, with the address it is served on in the `subjectAltName`. The run prints
its SHA-256 fingerprint, which is what an operator pins on the Prometheus side.
A certificate within `deploy_otel_collector_tls_renew_before_days` of expiry is
replaced on the next run, and the collector restarted.

Point the two variables at a certificate of the site PKI to replace it. The
role then copies those and signs nothing.

Either way, what TLS alone buys is confidentiality: anyone who reaches the
administration network and accepts the certificate still reads the metrics.
`deploy_otel_collector_tls_client_ca` is what turns it into access control,
and it works with the self-signed server certificate too.

## Role Variables

| Variable | Required | Type | Default | Comments |
|---|---|---|---|---|
| `deploy_otel_collector_enabled` | No | Boolean | `false` | Deploy the collector, and move the exporters to the loopback |
| `deploy_otel_collector_image` | No | String | pinned contrib image | Collector image, pinned to a reviewed version |
| `deploy_otel_collector_listen_address` | No | String | `"{{ ip_addr \| default(ansible_host) }}"` | Address the single endpoint is served on |
| `deploy_otel_collector_listen_port` | No | Integer | `9464` | Port of the single endpoint |
| `deploy_otel_collector_tls_cert` | No | String | undefined | Server certificate, path on the Ansible machine; the node signs its own without it |
| `deploy_otel_collector_tls_key` | No | String | undefined | Server key, path on the Ansible machine |
| `deploy_otel_collector_tls_self_signed` | No | Boolean | `true` | Sign a certificate on the node when none is given |
| `deploy_otel_collector_tls_self_signed_days` | No | Integer | `3650` | Validity of the certificate the node signs |
| `deploy_otel_collector_tls_renew_before_days` | No | Integer | `30` | Replace a certificate this close to expiry |
| `deploy_otel_collector_tls_client_ca` | No | String | undefined | CA client certificates are verified against, i.e. mutual TLS |
| `deploy_otel_collector_tls_min_version` | No | String | `"1.2"` | Minimum accepted TLS version |
| `deploy_otel_collector_cluster` | No | String | `""` | `cluster` label carried by every metric; empty means the target file keeps providing it |
| `deploy_otel_collector_nodename` | No | String | `""` | `nodename` label, same |
| `deploy_otel_collector_instance_address` | No | String | `"{{ ip_addr \| default(ansible_host) }}"` | Address the `instance` label is rewritten to |
| `deploy_otel_collector_scrape_interval` | No | String | `15s` | Interval the local endpoints are scraped at |
| `deploy_otel_collector_self_port` | No | Integer | `8888` | Loopback port the collector serves its own metrics on |
| `deploy_otel_collector_exporters` | No | List | from the inventory groups | Exporters to scrape on the loopback |
| `deploy_otel_collector_scrape_ceph` | No | Boolean | true on `cluster_machines` | Scrape the Ceph mgr `prometheus` module |
| `deploy_otel_collector_memory_limit_mib` | No | Integer | `256` | Memory ceiling the collector enforces on itself |
| `deploy_otel_collector_metric_expiration` | No | String | `30s` | How long a metric stays exposed without a fresh scrape |
| `deploy_otel_collector_cpu_affinity` | No | String | computed | Housekeeping CPUs; empty means the complement of `isolcpus` |
| `deploy_otel_collector_cpu_quota` | No | String | `25%` | `CPUQuota` of the unit |
| `deploy_otel_collector_nice` | No | Integer | `5` | `Nice` of the unit |
| `deploy_otel_collector_manage_services` | No | Boolean | `true` | Start the unit and restart it on changes |
| `deploy_otel_collector_register_essential_services` | No | Boolean | `true` | Publish the service for cukinia tests |

`cluster` and `nodename` are the join key the cluster dashboard reads, and
they are static labels of the Prometheus target file today. Left empty, which
is the default, this role does not touch them and they keep coming from there.
Setting both moves that identity to the node itself, for a site that would
rather not maintain a target file; since the scrape configuration below uses
`honor_labels`, what the node sends then wins, so the values have to be the
ones already in use.

Endpoints and job names are in `vars/main.yml`
(`deploy_otel_collector_target_map`). An exporter absent from that map fails
the run rather than silently dropping out of the scrape once the exporters have
moved to the loopback.

## Example inventory

```yaml
# group_vars/all.yml
deploy_otel_collector_enabled: true
deploy_otel_collector_cluster: siteA
```

That is enough: each node signs its own certificate. A site with a PKI gives
its own instead, and requires a client certificate from the scraper:

```yaml
deploy_otel_collector_tls_cert: /etc/seapath-pki/siteA/{{ inventory_hostname }}.crt
deploy_otel_collector_tls_key: /etc/seapath-pki/siteA/{{ inventory_hostname }}.key
deploy_otel_collector_tls_client_ca: /etc/seapath-pki/siteA/prometheus-ca.crt
```

Then:

```bash
ansible-playbook playbooks/seapath_setup_prometheus_exporters.yaml
```

## On the Prometheus side

One target per node, over HTTPS, with a client certificate when
`deploy_otel_collector_tls_client_ca` is set:

```yaml
scrape_configs:
  - job_name: seapath
    scheme: https
    # The collector already carries the job, instance, cluster and nodename of
    # each series. Without this, Prometheus renames them exported_job,
    # exported_instance and so on, and every dashboard filtering on them breaks.
    honor_labels: true
    tls_config:
      # The CA of the site PKI, or the certificate a node signed itself, which
      # is then pinned per node and checked against the fingerprint the run
      # printed. cert_file and key_file are what
      # deploy_otel_collector_tls_client_ca asks for.
      ca_file: /etc/prometheus/seapath-ca.crt
      cert_file: /etc/prometheus/prometheus.crt
      key_file: /etc/prometheus/prometheus.key
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
    relabel_configs:
      - source_labels: [__address__]
        regex: "(.+)"
        target_label: __address__
        replacement: "${1}:9464"
```

This replaces the six jobs and their `keep` relabel rules documented in
[PROMETHEUS.md](../seapath_alloc/PROMETHEUS.md): the per-node collector
scrapes what the node actually runs, so a job that does not apply to a host
simply has no target there. The `cluster`, `nodename` and `instance` labels
keep the values they have today, which is what the bundled Grafana dashboards
read.

## What it costs

- **A component to follow.** `opentelemetry-collector-contrib` releases every
  two weeks, and component configuration moves between releases. The image is
  pinned here and raising it is a reviewed change, with the CVE watch that
  comes with it.
- **CPU and memory on a real-time machine.** The unit is pinned to the
  housekeeping CPUs, quota'd and reniced, and the collector enforces its own
  memory ceiling. Measure it on a bench before a substation.
- **An extra hop.** A metric is now at most one scrape interval older than it
  used to be, and a collector that is down hides the node's whole
  observability. It is registered as an essential service so cukinia tests
  report it.
- **A stale copy when one series of a metric disappears.** An exporter that
  dies takes its series with it: the receiver marks them stale and the
  collector stops serving them at the next scrape, leaving `up=0` for that job.
  The case to know about is a series that disappears while its exporter keeps
  answering. The collector's accumulator removes one such series per metric per
  scrape and keeps serving the others until
  `deploy_otel_collector_metric_expiration` elapses, so an endpoint can report
  a label set the exporter has stopped publishing beside the one that replaced
  it. That is why the default is two scrape intervals. Measured on
  opentelemetry-collector-contrib 0.161.0. Alert on `up`.

What it does not cost is startup ordering: a target that is not up yet is a
scrape that fails, reported as `up=0` and retried, so the unit is ordered
behind nothing but the network.
