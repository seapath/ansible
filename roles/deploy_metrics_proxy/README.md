# Deploy metrics proxy Role

This role deploys one TLS reverse proxy per node, nginx as a Podman quadlet
container unit under `/etc/containers/systemd/`, in front of the Prometheus
exporters `deploy_prometheus_exporters` and `cephadm` deploy.

The proxy reaches those exporters on `127.0.0.1` and serves each of them on
its own path of a single TLS endpoint, `/metrics/<job>`. Turning it on with
`deploy_metrics_proxy_enabled` also moves the exporters to the loopback: both
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
none of them is configured for it here. One proxy in front means one
certificate to deploy and rotate, one TLS policy to audit, and one port.

The proxy forwards bytes. Each exposition reaches Prometheus exactly as its
exporter wrote it, each exporter stays its own Prometheus job with its own
`up`, and nothing on the node parses, merges or caches a metric.

| Path | Exporter | Loopback port |
|---|---|---|
| `/metrics/node` | node-exporter | 9100 |
| `/metrics/ceph` | Ceph mgr `prometheus` module | 9283 |
| `/metrics/ha` | ha_cluster_exporter | 9664 |
| `/metrics/seapath_custom_exporter` | insatomcat-exporter | 9184 |
| `/metrics/libvirt_exporter` | libvirt-exporter | 9177 |
| `/metrics/podman_exporter` | podman-exporter | 9882 |

A node serves only the paths of the exporters it runs. Any other path answers
404, and a path whose exporter is not answering yet answers 502.

## Requirements

- Podman with quadlet/systemd container support
- `openssl` on the node, when it signs its own certificate
- `deploy_prometheus_exporters` deployed on the same host, normally in the same
  play (`playbooks/seapath_setup_prometheus_exporters.yaml`)

## Certificates

Nothing has to be provided: without `deploy_metrics_proxy_tls_cert` and
`deploy_metrics_proxy_tls_key`, the node signs its own certificate, valid ten
years, with the address it is served on in the `subjectAltName`. The run prints
its SHA-256 fingerprint, which is what an operator pins on the Prometheus side.
A certificate within `deploy_metrics_proxy_tls_renew_before_days` of expiry is
replaced on the next run, and the proxy restarted.

Point the two variables at a certificate of the site PKI to replace it. The
role then copies those and signs nothing.

Either way, what TLS alone buys is confidentiality: anyone who reaches the
administration network and accepts the certificate still reads the metrics.
`deploy_metrics_proxy_tls_client_ca` is what turns it into access control,
and it works with the self-signed server certificate too.

## Role Variables

| Variable | Required | Type | Default | Comments |
|---|---|---|---|---|
| `deploy_metrics_proxy_enabled` | No | Boolean | `false` | Deploy the proxy, and move the exporters to the loopback |
| `deploy_metrics_proxy_image` | No | String | pinned nginx image | Proxy image, pinned to a reviewed version |
| `deploy_metrics_proxy_listen_address` | No | String | `"{{ ip_addr \| default(ansible_host) }}"` | Address the single endpoint is served on |
| `deploy_metrics_proxy_listen_port` | No | Integer | `9464` | Port of the single endpoint |
| `deploy_metrics_proxy_tls_cert` | No | String | undefined | Server certificate, path on the Ansible machine; the node signs its own without it |
| `deploy_metrics_proxy_tls_key` | No | String | undefined | Server key, path on the Ansible machine |
| `deploy_metrics_proxy_tls_self_signed` | No | Boolean | `true` | Sign a certificate on the node when none is given |
| `deploy_metrics_proxy_tls_self_signed_days` | No | Integer | `3650` | Validity of the certificate the node signs |
| `deploy_metrics_proxy_tls_renew_before_days` | No | Integer | `30` | Replace a certificate this close to expiry |
| `deploy_metrics_proxy_tls_client_ca` | No | String | undefined | CA client certificates are verified against, i.e. mutual TLS |
| `deploy_metrics_proxy_tls_min_version` | No | String | `"1.2"` | Minimum accepted TLS version, `1.2` or `1.3` |
| `deploy_metrics_proxy_read_timeout` | No | String | `8s` | How long the proxy waits for an exporter before answering 504 |
| `deploy_metrics_proxy_exporters` | No | List | from the inventory groups | Exporters to serve |
| `deploy_metrics_proxy_serve_ceph` | No | Boolean | true on `cluster_machines` | Serve the Ceph mgr `prometheus` module |
| `deploy_metrics_proxy_cpu_affinity` | No | String | computed | Housekeeping CPUs; empty means the complement of `isolcpus` |
| `deploy_metrics_proxy_cpu_quota` | No | String | `25%` | `CPUQuota` of the unit |
| `deploy_metrics_proxy_nice` | No | Integer | `5` | `Nice` of the unit |
| `deploy_metrics_proxy_manage_services` | No | Boolean | `true` | Start the unit and restart it on changes |
| `deploy_metrics_proxy_register_essential_services` | No | Boolean | `true` | Publish the service for cukinia tests |

Ports and job names are in `vars/main.yml` (`deploy_metrics_proxy_target_map`).
An exporter absent from that map fails the run rather than silently becoming
unreachable once the exporters have moved to the loopback.

## Example inventory

```yaml
# group_vars/all.yml
deploy_metrics_proxy_enabled: true
```

That is enough: each node signs its own certificate. A site with a PKI gives
its own instead, and requires a client certificate from the scraper:

```yaml
deploy_metrics_proxy_tls_cert: /etc/seapath-pki/siteA/{{ inventory_hostname }}.crt
deploy_metrics_proxy_tls_key: /etc/seapath-pki/siteA/{{ inventory_hostname }}.key
deploy_metrics_proxy_tls_client_ca: /etc/seapath-pki/siteA/prometheus-ca.crt
```

Then:

```bash
ansible-playbook playbooks/seapath_setup_prometheus_exporters.yaml
```

## On the Prometheus side

The six jobs of [PROMETHEUS.md](../seapath_alloc/PROMETHEUS.md) stay,
with their `keep` rules. A `proxy: "true"` label on a target switches that host
to HTTPS, the path of its exporter and the port of the proxy, and keeps the
`instance` it had, so nodes move behind the proxy one at a time: see
[its proxy section](../seapath_alloc/PROMETHEUS.md#behind-the-per-node-metrics-proxy).

Deploy the role on a node first, then add the label: in between, the exporters
of that node are on the loopback and its targets are down.

## What it costs

- **A component to follow.** nginx is pinned here, and raising it is a
  reviewed change with the CVE watch that comes with it. The slim image holds
  nginx and its core modules, nothing else.
- **CPU on a real-time machine.** One worker, pinned to the housekeeping CPUs,
  quota'd and reniced. It forwards a handful of scrapes per interval and keeps
  no state between them.
- **A single point for the node's observability.** A proxy that is down makes
  every job of the node go down at once. It is registered as an essential
  service so cukinia tests report it.

What it does not cost is startup ordering: an exporter that is not up yet
answers 502 through the proxy, which Prometheus reports as that job being down
and retries, so the unit is ordered behind nothing but the network.
