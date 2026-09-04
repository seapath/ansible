# seapath_alloc

Deploys the SEAPATH CPU allocation system on hypervisor nodes.

The allocation system manages a pool of isolated CPU cores (`isolcpus=` kernel
parameter) and assigns them to the threads of virtual machines when they
start, so that two VMs never get the same core. NIC IRQs and other threads
already pinned to isolated cores are counted as occupied.

## Requirements

- libvirt 10.4.0 or later, for VM threads left unpinned to stay off the
  isolated cores (see [ARCHITECTURE.md](ARCHITECTURE.md#requirements)).
- PyYAML on the hypervisor (`python3-yaml` on Debian, `python3-pyyaml` on
  CentOS and OracleLinux, `python3-PyYAML` on SLES). The role installs it with the `package-install` tag and fails
  if it is missing.

## Role variables

| Variable | Default | Description |
|----------|---------|-------------|
| `seapath_alloc_strategy` | `spreading` | Allocation strategy written to `/etc/seapath/alloc.yaml`. Valid values: `spreading`, `packing`, `repacking`. See [Allocation strategies](#allocation-strategies) below. |

## How the pool works

The pool's state is derived from the kernel at every allocation request:
thread affinities from `/proc`, NIC MSI-IRQ affinities from `/proc/irq` and
`/sys`. An isolated core is occupied as soon as a userspace thread is pinned
there, whoever pinned it: a VM, a quadlet with `CPUAffinity=`, a tool started
with `taskset`. Pinning that works without seapath-alloc keeps working with it.

There is no daemon. The hook reads the pool state fresh on each invocation
under an exclusive `flock` on `/run/seapath/alloc/.lock`, so concurrent starts
(two VMs migrating in simultaneously) are safe. When a VM stops, its threads
leave `/proc` and its cores are free again, with no release step.

### Isolation levels

| Level | Cores allocated | HT sibling |
|-------|-----------------|------------|
| `exclusive_logical` | 1 logical core | stays in the pool: another actor may get it |
| `exclusive_physical` | 1 logical core | reserved and left idle |
| `none` | none (left unpinned; runs on housekeeping cores) | n/a |

### Fallback hierarchy

When a requested level cannot be satisfied the allocator degrades gracefully rather than aborting the VM:

| Requested | Fallback 1 | Fallback 2 |
|-----------|-----------|-----------|
| `exclusive_physical` | `exclusive_logical`: RT isolation preserved, HT sibling not reserved | housekeeping: no RT isolation |
| `exclusive_logical` | (none) | housekeeping: no RT isolation |

A group with `count` that gets only part of its cores keeps them (an
`exclusive_physical` group first tops the missing ones up with logical cores).

Each degradation is logged to `/var/log/seapath/alloc.log` with its severity:

- warning, RT isolation preserved with less than asked: `"degraded to exclusive_logical"`, `"only N/M ... available"`.
- error, no RT isolation: `"falling back to housekeeping"`, or an unknown isolation in the profile. A `FIFO` or `RR` policy is then dropped to `OTHER`: an RT thread among Ceph, corosync and the kworkers could starve them, with only RT throttling as a guard.

## Deployed files

| Path | Purpose |
|------|---------|
| `/usr/lib/seapath/seapath_alloc/` | Python package (topology, pool, allocator, ...) |
| `/usr/bin/seapath-alloc` | CLI status tool |
| `/usr/bin/seapath-qemu-hook` | libvirt hook entry point |
| `/usr/bin/seapath-container-pin` | Pin a systemd service to an isolated core |
| `/usr/bin/seapath-container-unpin` | Release the pin for a systemd service |
| `/usr/bin/seapath-run` | Launch a third-party binary on an isolated core |
| `/etc/libvirt/hooks/qemu.d/10-seapath-pinning` | Symlink → seapath-qemu-hook |
| `/etc/seapath/alloc.yaml` | Host-wide settings (`allocation_strategy`) |

libvirt only discovers hook scripts when its QEMU daemon starts (`virtqemud`
on OracleLinux, `libvirtd` elsewhere). When the hook is first registered, the
role restarts whichever of them is running; running VMs keep running. Under
Pacemaker, a `VirtualDomain` monitor that runs during the restart falls back
to checking the QEMU process, but a start, stop or migration at that moment
can fail: deploy the role before the VMs, or with the cluster in maintenance
mode.

## Use cases

### 1. Virtual machines (libvirt hook)

The hook `/etc/libvirt/hooks/qemu.d/10-seapath-pinning` is called automatically
by libvirt on every VM start and migration.

Pinning is configured per VM via Ceph RBD image metadata on its system disk:
the RBD image named `system_<vm>` (the vm_manager naming), or else the first
RBD disk of the domain.

```bash
rbd image-meta set rbd/system_<vm> _seapath_alloc '
version: 1
vcpus:
  isolation: exclusive_physical
  scheduler: FIFO
  priority: 90
emulator:
  isolation: exclusive_logical
  scheduler: FIFO
  priority: 50
vhost:
  isolation: exclusive_logical
  scheduler: FIFO
  priority: 50
'
```

The profile travels with the disk, so a VM migrating to another node is
re-allocated there against that node's own topology, with nothing to configure
per node. The VM picks up a new profile at its next start or migration.

If no metadata is present for a VM, all thread groups run on housekeeping
cores with no RT scheduling (`isolation: none, scheduler: OTHER`). This is the
intended behaviour for non-RT VMs: no configuration is needed to leave a VM
unpinned, and a VM pinned by a static `<cputune>` block in its XML keeps
exactly that. Setting a profile on a VM that also has `<cputune>` pins makes
the profile win, with a warning in the log: use one or the other.

If the metadata cannot be read (Ceph unreachable, invalid YAML), the VM starts
unpinned and the hook logs an error.

The hook acts on `started/begin`, which libvirt sends for a normal start and
on the destination host of a live migration. It always exits 0: if pinning
fails the VM starts anyway and the error is logged to
`/var/log/seapath/alloc.log`.

#### Profile key defaults

All keys are optional. Missing keys are filled according to these rules, applied
in order:

1. **Absent group** (`iothread`, `vhost`, ...): equivalent to writing the group
   with an empty body: all sub-keys filled from the built-in defaults below.
2. **Isolation without scheduler**: if `isolation` is anything other than `none`
   and `scheduler` is not specified, `scheduler` defaults to `FIFO` (non-none
   isolation implies RT intent).
3. **RT scheduler without priority**: if `scheduler` is `FIFO` or `RR` and
   `priority` is not specified, `priority` defaults to `1` (minimum valid RT
   priority, which avoids a `chrt` failure).
4. **OTHER / BATCH**: `priority` is always forced to `0` regardless of what is
   written.

Values are validated when the profile is read: `isolation` and `scheduler` are
case-insensitive and an RT priority outside 1-99 is clamped. An unknown
`scheduler` is logged as an error and replaced by `OTHER`; an unknown
`isolation` is logged as an error and leaves the group unpinned on `OTHER`,
reported as a hard fallback.

Built-in values (applied before the rules above):

| Sub-key | Built-in default |
|---------|-----------------|
| `isolation` | `none` |
| `scheduler` | `OTHER` |
| `priority` | `0` |

Practical examples:

```yaml
# Only isolation specified → scheduler inferred as FIFO, priority as 1
vcpus:
  isolation: exclusive_physical

# Only scheduler specified → priority inferred as 1
emulator:
  scheduler: FIFO

# Explicit priority always wins
vhost:
  isolation: exclusive_logical
  scheduler: FIFO
  priority: 50
```

#### Per-vCPU profiles

vCPUs can be configured uniformly (one dict for all) or individually (list
indexed by vCPU number, last entry repeated for any remainder). The vCPU
number is the one QEMU gives the thread (`CPU <n>/KVM`):

```yaml
vcpus:
  - isolation: exclusive_physical   # vCPU 0: RT
    scheduler: FIFO
    priority: 90
  - isolation: none                  # vCPUs 1+: housekeeping
    scheduler: OTHER
    priority: 0
```

#### Allocation strategies

The strategy is set host-wide via the `seapath_alloc_strategy` Ansible variable
(written to `/etc/seapath/alloc.yaml`).  It applies to both VM thread groups
and `seapath-run` / container claims.

| Strategy | Behaviour |
|----------|-----------|
| `spreading` | one thread per physical core first, whatever the sibling numbering (default; best HT noise isolation) |
| `packing` | fill both HT siblings before using the next physical core |
| `repacking` | spreading, but compacts existing VMs' logical threads into half-used pairs first to free physical pairs when an `exclusive_physical` allocation is requested and no free pair is available |

Set the strategy in your inventory:

```yaml
# group_vars/hypervisors.yml
seapath_alloc_strategy: repacking
```

Or per host:

```yaml
# host_vars/node1.yml
seapath_alloc_strategy: packing
```

### 2. Containers (systemd quadlets)

Use `seapath-container-pin` and `seapath-container-unpin` from `ExecStartPost=`
and `ExecStopPost=` in the quadlet unit file:

```ini
[Container]
Image=...

[Service]
ExecStartPost=seapath-container-pin %p exclusive_logical FIFO 80
ExecStopPost=-seapath-container-unpin %p
```

`seapath-container-pin <service> <isolation> <scheduler> <priority>`

- Allocates one isolated core via the pool.
- Confines the container (Podman's `libpod-payload-*` sub-cgroup) to that
  core, and conmon and systemd's `.control` to the housekeeping cores, by
  writing `cpuset.cpus` at each level and the affinity of each thread.
- Applies the scheduling policy to every thread of the container, including
  those it started before the pin. conmon keeps SCHED_OTHER.
- A service without a `libpod-payload-*` sub-cgroup is pinned as a whole:
  every thread of its cgroup tree gets the core and the policy.

Rationale in [ARCHITECTURE.md](ARCHITECTURE.md), data flow 2.

`seapath-container-unpin <service>` releases the claim.

The service name may be given with or without the `.service` suffix.

### 3. NIC IRQ threads

NIC IRQ occupancy is tracked **passively**: the pool reads the affinity of
each NIC IRQ on every invocation (`/proc/irq/<n>/effective_affinity_list`,
or `smp_affinity_list` when the kernel does not expose the effective one) and
treats the isolated cores of an IRQ routed only to isolated cores as
occupied, with no explicit registration step. An IRQ left on its default
all-CPUs affinity occupies nothing.

Only IRQs belonging to a physical NIC (enumerated via
`/sys/class/net/*/device/msi_irqs/`) are counted. Kernel-managed MSI IRQs
(NVMe, xHCI, ...) that the driver subsystem may route to isolated CPUs under
`isolcpus=managed_irq` are excluded deliberately.

This means that once the `configure_nic_irq_affinity` monitor daemon pins a
NIC queue to an isolated core, that core is automatically unavailable to VMs
without any coordination between the two roles.

### 4. Third-party processes (seapath-run)

For any binary that cannot be modified, use `seapath-run` as a wrapper:

```bash
seapath-run <label> <isolation> <scheduler> <priority> -- <command> [args...]
```

`seapath-run`:
1. Allocates cores from the pool and registers the claim under `label`.
2. Applies `taskset -cp` and `chrt` to itself.
3. Launches `command` as a child process. The child inherits CPU affinity and
   RT scheduling automatically via `fork`/`exec` — no modification to the
   binary is required.
4. On child exit (or SIGTERM/SIGINT, which are forwarded to the child),
   releases the claim.

The command must stay in the foreground (`Type=simple` in a systemd unit): a
command that forks into the background makes `seapath-run` release the claim
at once while the daemon keeps the cores. A FIFO or RR request that finds no
free isolated core is refused (exit 1) rather than run as OTHER on the
housekeeping cores.

Example — IEC 61850 Sampled Values publisher:

```bash
seapath-run sv-sim exclusive_logical FIFO 80 -- \
    /usr/bin/sv-simulator -i eth0
```

Exits with the child's exit code. Signal-terminated children produce exit code
`128 + signal_number` (standard shell convention), and a command that cannot
be started gives 127 (not found) or 126 (not executable).

## Checking pool state

```bash
seapath-alloc status
```

Prints a table of all currently occupied isolated cores and the actor holding
each one (VM name, container service name, IRQ number, or claim label). A
process pinned to isolated cores without seapath-alloc (a quadlet with
`CPUAffinity=`, a tool started with `taskset`) holds its cores too and is
listed as `pinned`, `<comm>[<pid>]`.

## Log output

The libvirt hook writes to `/var/log/seapath/alloc.log` (rotated weekly via
`/etc/logrotate.d/seapath-alloc`). Container pin/unpin and `seapath-run` write
to stderr (captured by journald when run from a systemd unit).

## Prometheus monitoring

For the Prometheus scrape configuration needed to feed the cluster-wide
dashboard (file-based service discovery, required `cluster`/`nodename`
labels, one job per exporter), see [PROMETHEUS.md](PROMETHEUS.md).

### Textfile collector

The role deploys a systemd timer (`seapath-alloc-export.timer`) that runs
`seapath-alloc export` every 15 seconds and writes
`/var/lib/prometheus/node_exporter/seapath-alloc.prom` in Prometheus textfile
format.  Configure your Prometheus node_exporter with
`--collector.textfile.directory=/var/lib/prometheus/node_exporter` (the default
for most packages) to pick it up automatically.

```bash
systemctl status seapath-alloc-export.timer   # check timer state
systemctl start seapath-alloc-export.service  # force an immediate run
journalctl -u seapath-alloc-export            # exporter logs
```

### Grafana dashboard

Import `roles/seapath_alloc/files/grafana-seapath-alloc.json` into
Grafana (Dashboards → Import).  The dashboard shows:

- **Pool Overview** — free cores, free pairs, active VM/IRQ/claim counts,
  fallback counter, metrics age (all with colour thresholds)
- **CPU Map** — one row per CPU with topology (isolated, HT pair, HT
  sibling), state, actor label, thread group, scheduler and priority;
  state column is colour-coded (green=free, blue=vm, orange=irq,
  purple=claim, gray=housekeeping)
- **VM Threads** — one row per QEMU thread with VM name, kernel comm,
  CPU(s), scheduler and RT priority
- **NIC IRQs** — interface, IRQ range, CPU
- **Claims** — label, CPU, scheduler, priority, PID
- **Allocation Failures** — rate graph + last-fallback context panel

### Exported metrics

**Summary gauges** (for alerting rules):

| Metric | Type | Description |
|--------|------|-------------|
| `seapath_alloc_isolated_cpus` | gauge | Total isolated CPUs on the node |
| `seapath_alloc_free_logical_cpus` | gauge | Free isolated logical cores |
| `seapath_alloc_free_physical_pairs` | gauge | Free isolated physical core pairs |
| `seapath_alloc_actors{type}` | gauge | Active actor count by type (`vm`, `irq`, `claim`) |
| `seapath_alloc_occupied_cpus{type}` | gauge | Occupied isolated CPUs by actor type |
| `seapath_alloc_vm_threads{vm}` | gauge | Pinned thread count per running VM |
| `seapath_alloc_active_fallbacks{severity}` | gauge | Actors **currently** running degraded: `severity=hard` (housekeeping, no RT isolation) or `severity=soft` (exclusive_logical instead of physical, RT preserved); auto-expires when the process exits |
| `seapath_alloc_active_fallback_info{label,group,requested,severity}` | gauge | One series per currently degraded actor (info metric, value=1) |
| `seapath_alloc_allocation_fallbacks_total` | counter | Cumulative degradation events (hard + soft) since last reset |
| `seapath_alloc_last_fallback_timestamp_seconds` | gauge | Timestamp of the most recent degradation event |
| `seapath_alloc_last_fallback_info{label,group,requested,severity}` | gauge | Context of the most recent degradation event (info metric) |
| `seapath_alloc_scrape_timestamp_seconds` | gauge | Timestamp when the timer last wrote the file |

**Detailed per-entity metrics** (for the Grafana CPU map):

| Metric | Type | Description |
|--------|------|-------------|
| `seapath_alloc_cpu_detail{cpu,isolated,ht_pair,ht_sibling,state,label,group,scheduler,priority}` | gauge | One series per CPU — full topology and occupancy context; `state` ∈ `free\|vm\|irq\|claim\|housekeeping` |
| `seapath_alloc_vm_thread_info{vm,thread,tid,cpu,scheduler,priority}` | gauge | One series per QEMU thread pinned on isolated cores |
| `seapath_alloc_irq_info{iface,irq_range,cpu}` | gauge | One series per NIC/IRQ group pinned on isolated cores |
| `seapath_alloc_claim_info{label,cpu,scheduler,priority,pid}` | gauge | One series per active claim (container or seapath-run process) |

Fallback state persists across reboots in
`/var/lib/seapath/alloc/fallbacks.json`.

**Host real-time tuning** (`seapath_rt_*`, written by `conformance.py`):

The metrics above say what the isolated cores are *doing*. These say what the
machine was *tuned as*, which `prometheus-node-exporter` publishes nowhere:
the tuned profile, the boot parameters, the RT throttling window, the hugepage
pools, SMT, transparent hugepages, the interrupt affinities and ACPI. They ride
in the same textfile, on the same timer, under the same `node` job.

They exist because that question has to be answerable for a whole cluster. A
management interface that wants to know whether five hypervisors still carry
the tuning their inventory declares otherwise has two options: read `/sys` on
the one node it happens to run on, or open an SSH connection per node on every
page refresh. One file read per timer tick on a host this collector already
runs on is cheaper than either.

| Metric | Type | Description |
|--------|------|-------------|
| `seapath_rt_tuned_info{profile,source,installed}` | gauge | The configured tuned profile (`/etc/tuned/active_profile`, never the running daemon's). `installed=0` means the profile is named but installed nowhere, so nothing is tuning the machine, which `tuned-adm active` does not tell you |
| `seapath_rt_kernel_cmdline_info{cmdline}` | gauge | The kernel command line, verbatim. Carries `isolcpus` **as requested**, which `/sys/devices/system/cpu/isolated` cannot show: the two differ on a machine converged and never rebooted |
| `seapath_rt_sched_rt_runtime_us` | gauge | Runtime an RT task may use per period. `-1` disables throttling, which is what the realtime profile sets |
| `seapath_rt_sched_rt_period_us` | gauge | The throttling period |
| `seapath_rt_hugepages_total{size_kb,node}` | gauge | Hugepages reserved. `node` is empty for the machine-wide pool and carries the NUMA node number otherwise: a guest pinned to one socket draws from that socket's pool, so the right total with an empty node is a guest that fails to start |
| `seapath_rt_hugepages_free{size_kb,node}` | gauge | Hugepages still free, same labels |
| `seapath_rt_transparent_hugepages_info{enabled,defrag}` | gauge | Anything but `never` leaves khugepaged compacting memory in the background, which an isolated CPU does not escape |
| `seapath_rt_smt_info{control}` | gauge | The SMT control the machine exposes, empty where it exposes none (usual on AMD and where the firmware disabled SMT) |
| `seapath_rt_smt_active` | gauge | 1 when two threads share a core's execution units, so an isolated CPU is only isolated if its sibling is idle or isolated too |
| `seapath_rt_acpi_present` | gauge | 1 when the firmware exposes ACPI. Nothing here measures an SMI: they are invisible to the kernel by construction, and `hwlatdetect` is what measures them |
| `seapath_rt_irqs_total` | gauge | Interrupts the machine has a descriptor for |
| `seapath_rt_irqs_on_isolated_cpus` | gauge | Interrupts whose affinity mask still reaches an isolated CPU. A mask is a permission rather than a measurement: the interrupt is a latency source whether or not it has fired there yet. `0` is the expected shape where the kernel honours `isolcpus=managed_irq` |
| `seapath_rt_nic_irqs_pinned_to_isolated_cpus` | gauge | Among them, the physical NIC interrupts confined to isolated CPUs: the shape `configure_nic_irq_affinity` gives on purpose |
| `seapath_rt_irq_on_isolated_info{irq,name,cpus,nic}` | gauge | One series per such interrupt, naming the device behind it; `nic="1"` for a NIC interrupt confined to isolated CPUs. At most 8 are described; the gauge above always carries the true count |

Two conventions the consumers rely on, both asserted by the test suite:

- **An info family is published even when the reading came back empty.** An
  empty `profile` label means "read, and there is none"; an absent
  `seapath_rt_tuned_info` means "this node runs a collector too old to publish
  the block". Those are different faults with different fixes, and a consumer
  can tell them apart.
- **A numeric gauge is omitted when it could not be read**, never defaulted,
  because every value it could carry is a legitimate one: `-1` is a correctly
  tuned `sched_rt_runtime_us`, and a hugepage pool of `0` is a real answer.

Nothing in this block is a verdict. Whether a value is right for a given
machine depends on what that machine's inventory declares, which this collector
does not have: it reports what it read, and whoever holds the inventory decides
what it means.

### Recommended alerting rules

```yaml
groups:
  - name: seapath_alloc
    rules:
      - alert: SeapathAllocPoolExhausted
        expr: seapath_alloc_free_logical_cpus == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "No free isolated logical cores on {{ $labels.instance }}"
          description: >
            All isolated logical cores are occupied. New VMs or containers
            will run on housekeeping cores without RT guarantees.

      - alert: SeapathAllocNoPhysicalPairs
        expr: seapath_alloc_free_physical_pairs == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "No free isolated physical pairs on {{ $labels.instance }}"
          description: >
            No full physical core pair is available. VMs requesting
            exclusive_physical isolation will fall back to housekeeping.

      - alert: SeapathAllocFallback
        expr: increase(seapath_alloc_allocation_fallbacks_total[5m]) > 0
        labels:
          severity: critical
        annotations:
          summary: "RT allocation fallback on {{ $labels.instance }}"
          description: >
            At least one VM or process could not get isolated cores and is
            running without RT guarantees. Check hook.log for details.

      - alert: SeapathRtProfileNotInstalled
        expr: seapath_rt_tuned_info{installed="0"} == 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "tuned profile installed nowhere on {{ $labels.instance }}"
          description: >
            {{ $labels.profile }} is selected in /etc/tuned/active_profile but
            no profile of that name is installed, so nothing is tuning this
            machine. tuned-adm active reports the name either way.

      - alert: SeapathAllocMetricsStale
        expr: time() - seapath_alloc_scrape_timestamp_seconds > 120
        labels:
          severity: warning
        annotations:
          summary: "seapath-alloc metrics stale on {{ $labels.instance }}"
          description: >
            The seapath-alloc-export timer has not run for more than 2 minutes.
            Check: systemctl status seapath-alloc-export.timer
```
