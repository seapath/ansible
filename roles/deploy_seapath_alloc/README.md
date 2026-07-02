# deploy_seapath_alloc

Deploys the SEAPATH CPU allocation system on hypervisor nodes.

The allocation system manages a pool of isolated CPU cores (`isolcpus=` kernel
parameter) and distributes them across four categories of actors: virtual
machines, containers, NIC IRQ threads, and third-party real-time processes.
All actors share the same pool and cannot double-allocate the same core.

## Role variables

| Variable | Default | Description |
|----------|---------|-------------|
| `seapath_alloc_strategy` | `spreading` | Allocation strategy written to `/etc/seapath/alloc.yaml`. Valid values: `spreading`, `packing`, `repacking`. See [Allocation strategies](#allocation-strategies) below. |

## How the pool works

The pool's state is derived from two sources that are combined at every
allocation request:

| Source | What it tracks |
|--------|----------------|
| Kernel `/proc` and `/sys` | QEMU thread affinities, NIC MSI-IRQ affinities |
| `/run/seapath/alloc/claims.json` | Container and third-party process claims |

There is no daemon. Every tool reads the pool state fresh on each invocation
under an exclusive `flock` on `/run/seapath/alloc/.lock`, so concurrent starts
(two VMs migrating in simultaneously) are safe.

Claims in `claims.json` self-heal: an entry whose PID is no longer present in
`/proc` is silently dropped the next time the pool is read — no explicit
release is needed after a crash.

### Isolation levels

| Level | Cores allocated | HT sibling |
|-------|-----------------|------------|
| `exclusive_logical` | 1 logical core | sibling stays free |
| `exclusive_physical` | 1 logical core | sibling reserved (idle) |
| `none` | none (left unpinned; runs on housekeeping cores) | n/a |

### Shared-core slots (colocation)

`exclusive_*` means alone on the core: the RT priority never arbitrates
between actors, and a whole core is wasted on actors that use very little CPU
(an IRQ thread, an emulator). A **slot** is a named group of isolated cores
that several actors share, each with its own scheduler and priority:

- the **first** actor referencing the name allocates the slot's cores through
  the normal isolation paths (`isolation` then describes the *slot's* level,
  default `exclusive_logical`; the usual degradation chain applies);
- **later** actors referencing the same name run on the same cores without
  consuming anything from the pool;
- the slot's cores stay busy for every normal allocation, and the slot
  expires automatically once no live actor occupies any of its cores.

How a slot comes into existence depends on whether the actor moves:

- **Mobile actors** (VM thread groups, containers, `seapath-run` processes)
  migrate between cluster nodes, so their cores cannot be decided per-node in
  advance: their slots are **allocated from the pool** at first reference, as
  described above.
- **Fixed actors** (NIC IRQs — the NIC is local to the server, its IRQs exist
  from boot to shutdown) have no placement problem to solve: the operator
  already chose the core in the inventory. They **declare** their slot on
  that core (`slot=<name>:<cpu>` in `nic-irq-affinity.conf`); the IRQ pinning
  itself never depends on seapath-alloc, the declaration only opens the door
  for joiners.

The rule of thumb: **the fixed actor publishes its position, mobile actors
join it by name** — never the reverse.

**`count` and `slot` compose**: `count` sizes the shared core group, `slot`
names and publishes it. A `count` group without a `slot` (the historical
`vhost`/`iothread` form below) is an *anonymous private slot*: same shared
cpuset, but scoped to that thread group of that VM, joinable by nobody, and
needing no entry in `slots.json` (with no joiners, liveness from `/proc`
suffices). Adding `slot:` to the same spec makes that group public:

**Mind the mode switch**: either key (`slot` or `count`) moves the spec from
*exclusive per-thread* mode to *shared group* mode, and the two modes have
opposite defaults. Without both keys, each thread of the group gets its own
core (maximum isolation — the safe RT default). With `slot:` and no `count`,
the group defaults to **one** core: writing `vhost: {slot: x}` on a VM with
four vhost threads puts all four on a single core. Sharing is the point of a
slot, so its default is the minimum footprint — say `count: N` if the group
needs more room. `count` itself always means the same thing: the size of the
shared core group.

```yaml
vhost:
  slot: fastpath   # 2-core slot created here…
  count: 2
  scheduler: FIFO
  priority: 1      # …and joinable by any other actor as slot:fastpath
```

Slot names are **host-global**: the same name in a VM profile, a quadlet, a
`seapath-run` call or `/etc/nic-irq-affinity.conf` designates the same cores.
That is the coordination mechanism, and it is what makes clusters work with
no per-node configuration in the profiles: `slot: sv0` in a VM's RBD metadata
resolves on whichever node the VM lands on, to *that node's* `sv0` (e.g. the
core declared by its local NIC). The flip side: generic names copy-pasted
between unrelated profiles will colocate them by accident. Pick explicit
names.

Attributes (`isolation`, `count`) are fixed when the slot is created. Within
one allocation round (one VM profile), every spec referencing the slot
co-defines it — size is the largest `count` requested, isolation the
strongest — so the internal expansion order (vcpus → emulator → vhost) does
not matter: `vhost: {slot: x, count: 2}` sizes the slot even though the
emulator referencing `x` is allocated first. Across rounds (another VM,
another actor), the slot already exists: a joiner requesting different
attributes joins as-is with a logged warning. If the slot's creation fell
back to housekeeping, the slot is not persisted and each member degrades
individually.

Two canonical use cases:

```yaml
# VM profile: emulator in TS and vhost in FIFO/1 on the same single core
emulator:
  slot: housework
  scheduler: OTHER
vhost:
  slot: housework
  scheduler: FIFO
  priority: 1
```

```bash
# Share the core of eth0's IRQs (declared as slot=sv0:14 in
# /etc/nic-irq-affinity.conf) below the FIFO/50 irq threads:
seapath-run sv-proc slot:sv0 FIFO 10 -- /usr/bin/sv-consumer -i eth0
```

Anything may join a slot, including vCPUs — the logic is fully generic.
Risky combinations are never refused, but they are logged and exported as
`seapath_alloc_slot_warning_info` metrics:

| Reason | Pattern |
|--------|---------|
| `equal_rt_priority` | two distinct actors with the same FIFO/RR priority — neither preempts the other, mutual starvation is possible |
| `rt_priority_ge_irq` | a FIFO/RR member at priority ≥ 50 shares the slot with NIC IRQs (irq threads run FIFO/50) — interrupt handling can starve |
| `vcpu_shared` | a vCPU shares the slot — preempting a guest CPU while its kernel holds a spinlock can stall the guest (RCU, soft lockups) |

The full rationale behind these choices (creation follows actor mobility,
one global namespace, creator-fixed attributes, never refuse — always warn,
observed membership) is documented in
[ARCHITECTURE.md](ARCHITECTURE.md#shared-core-slots--model-and-rationale).

### Fallback hierarchy

When a requested level cannot be satisfied the allocator degrades gracefully rather than aborting the VM:

| Requested | Fallback 1 | Fallback 2 |
|-----------|-----------|-----------|
| `exclusive_physical` | `exclusive_logical` — RT isolation preserved, HT sibling not reserved | housekeeping — no RT isolation |
| `exclusive_logical` | — | housekeeping — no RT isolation |

Each degradation emits a warning that distinguishes the two outcomes:
- `"degraded to exclusive_logical"` — RT scheduling still applies; only the HT-sibling noise guarantee is lost.
- `"falling back to housekeeping"` — no isolation; thread competes on shared cores.

Both trigger `record_fallback()` and increment the `seapath_alloc_allocation_fallbacks_total` Prometheus counter.

## Deployed files

| Path | Purpose |
|------|---------|
| `/usr/lib/seapath/seapath_alloc/` | Python package (topology, pool, allocator, …) |
| `/usr/bin/seapath-alloc` | CLI status tool |
| `/usr/bin/seapath-qemu-hook` | libvirt hook entry point |
| `/usr/bin/seapath-container-pin` | Pin a systemd service to an isolated core |
| `/usr/bin/seapath-container-unpin` | Release the pin for a systemd service |
| `/usr/bin/seapath-run` | Launch a third-party binary on an isolated core |
| `/etc/libvirt/hooks/qemu.d/10-seapath-pinning` | Symlink → seapath-qemu-hook |
| `/etc/seapath/alloc.yaml` | Host-wide settings (`allocation_strategy`) |

## Use cases

### 1. Virtual machines (libvirt hook)

The hook `/etc/libvirt/hooks/qemu.d/10-seapath-pinning` is called automatically
by libvirt on every VM start and migration.

Pinning is configured per VM by a profile stored as Ceph RBD image metadata
under the key `_seapath_alloc`. The profile travels with the disk, so a VM
migrating to another node is re-allocated there against that node's own
topology, with nothing to configure per node.

**From the inventory (recommended).** Set `vm_pinning_profile` in the VM's
host variables; `deploy_vms_cluster` passes it to `vm_manager`, which writes
the RBD metadata at VM creation and propagates it on clone:

```yaml
# host_vars/myvm.yaml
vm_pinning_profile: |
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
```

The inventory stays the place where everything is authored, exactly as for
every other VM setting: RBD is where the profile lives and travels, not where
it is written.

**Directly on an existing VM.** The same profile can be set or updated on a
VM that already exists, without redeploying it:

```bash
rbd image-meta set rbd/<image> _seapath_alloc '
version: 1
vcpus:
  isolation: exclusive_physical
  scheduler: FIFO
  priority: 90
'
```

The VM picks up the new profile at its next start or migration.

If no metadata is present for a VM, all thread groups run on housekeeping
cores with no RT scheduling (`isolation: none, scheduler: OTHER`). This is the
intended behaviour for non-RT VMs: no configuration is needed to leave a VM
unpinned.

The hook acts on `started/begin` (normal start) and `started/incoming` (live
migration arrival). It always exits 0: if pinning fails the VM starts anyway
and the error is logged to `/var/log/seapath/alloc.log`.

#### Profile key defaults

All keys are optional. Missing keys are filled according to these rules, applied
in order:

1. **Absent group** (`iothread`, `vhost`, …): equivalent to writing the group
   with an empty body — all sub-keys filled from the built-in defaults below.
2. **Isolation without scheduler**: if `isolation` is anything other than `none`
   and `scheduler` is not specified, `scheduler` defaults to `FIFO` (non-none
   isolation implies RT intent). A `slot` reference without an explicit
   `isolation` implies `isolation: exclusive_logical` (a slot always has
   isolated cores to share; `isolation: none` with a slot is a warning and the
   slot is ignored).
3. **RT scheduler without priority**: if `scheduler` is `FIFO` or `RR` and
   `priority` is not specified, `priority` defaults to `1` (minimum valid RT
   priority — avoids `chrt` failure).
4. **OTHER / BATCH**: `priority` is always forced to `0` regardless of what is
   written.

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
indexed by vCPU number, last entry repeated for any remainder):

```yaml
vcpus:
  - isolation: exclusive_physical   # vCPU 0 — RT
    scheduler: FIFO
    priority: 90
  - isolation: none                  # vCPUs 1+ — housekeeping
    scheduler: OTHER
    priority: 0
```

#### Allocation strategies

The strategy is set host-wide via the `seapath_alloc_strategy` Ansible variable
(written to `/etc/seapath/alloc.yaml`).  It applies to both VM thread groups
and `seapath-run` / container claims.

| Strategy | Behaviour |
|----------|-----------|
| `spreading` | one thread per physical core (default; best HT noise isolation) |
| `packing` | fill both HT siblings before using the next physical core |
| `repacking` | spreading, but compacts existing VMs' logical threads first to free physical pairs when an `exclusive_physical` allocation is requested and no free pair is available |

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

`<isolation>` also accepts `slot:<name>[:<isolation>]` to join a named
shared-core slot instead of consuming a dedicated core (same grammar as
`seapath-run`).

- Allocates one isolated core via the pool.
- Writes `cpuset.cpus` at every level of the service cgroup tree (including
  Podman's `libpod-payload` sub-cgroup).
- Applies `taskset -cp` and `chrt` per PID.

`seapath-container-unpin <service>` releases the claim.

The service name may be given with or without the `.service` suffix.

### 3. NIC IRQ threads

The `configure_nic_irq_affinity` role deploys a monitor daemon
(`nic-irq-monitor.sh`) that pins NIC MSI-IRQ threads to the CPU configured in
`/etc/nic-irq-affinity.conf` whenever a managed interface comes up.

An interface's value may be a static CPU list, or `slot=<name>:<cpu>`: the
CPU comes from the inventory and is pinned unconditionally, exactly like a
static value, but the daemon additionally informs seapath-alloc
(`seapath-alloc slot <name> --cpus <cpu>`) that a slot exists on that core,
so other actors can join it by name later. Pinning never depends on
seapath-alloc being installed or the pool having room: worst case the slot
is not registered and only the colocation opportunity is lost.

The slot registration only marks the cores busy; NIC IRQ occupancy itself is
still tracked **passively**: the pool reads `/proc/irq/<n>/smp_affinity_list`
on every invocation and treats any isolated core already pinned by an IRQ as
occupied, with no explicit registration step.

Only IRQs belonging to a physical NIC (enumerated via
`/sys/class/net/*/device/msi_irqs/`) are counted. Kernel-managed MSI IRQs
(NVMe, xHCI, …) that the driver subsystem may route to isolated CPUs under
`isolcpus=managed_irq` are excluded deliberately.

This means that once the monitor daemon pins a NIC queue to an isolated core,
that core is automatically unavailable to VMs and containers without any
coordination between the two roles.

### 4. Third-party processes (seapath-run)

For any binary that cannot be modified, use `seapath-run` as a wrapper:

```bash
seapath-run <label> <isolation> <scheduler> <priority> -- <command> [args...]
```

`<isolation>` also accepts `slot:<name>[:<isolation>]` to join a named
shared-core slot (see [Shared-core slots](#shared-core-slots-colocation)).

`seapath-run`:
1. Allocates cores from the pool and registers the claim under `label`.
2. Applies `taskset -cp` and `chrt` to itself.
3. Launches `command` as a child process. The child inherits CPU affinity and
   RT scheduling automatically via `fork`/`exec` — no modification to the
   binary is required.
4. On child exit (or SIGTERM/SIGINT, which are forwarded to the child),
   releases the claim.

Example — IEC 61850 Sampled Values publisher:

```bash
seapath-run sv-sim exclusive_logical FIFO 80 -- \
    /usr/bin/sv-simulator -i eth0
```

Exits with the child's exit code. Signal-terminated children produce exit code
`128 + signal_number` (standard shell convention).

## Checking pool state

```bash
seapath-alloc status
```

Prints a table of all currently occupied isolated cores and the actor holding
each one (VM name, container service name, IRQ number, or claim label), plus
the active slots with their members.

Other subcommands:

| Subcommand | Purpose |
|------------|---------|
| `claim --label <l> [--isolation ...] [--scheduler ...] [--priority N] [--slot NAME] [--target-pid PID] [--no-apply]` | Register a claim manually (what `seapath-container-pin` and `seapath-run` use internally) |
| `release --label <l>` | Release a claim |
| `slot <name> --cpus LIST [--isolation ...]` | Declare a shared-core slot on operator-chosen cores so other actors can join it by name (never fails, conflicts are logged) |
| `spread [--dry-run]` | Move threads out of shared HT pairs into fully-free pairs (inverse of repacking compaction) |
| `export` | Write the Prometheus textfile (run by the systemd timer) |

## Log output

The libvirt hook writes to `/var/log/seapath/alloc.log` (rotated weekly via
`/etc/logrotate.d/seapath-alloc`). Container pin/unpin and `seapath-run` write
to stderr (captured by journald when run from a systemd unit).

## Prometheus monitoring

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

Import `roles/deploy_seapath_alloc/files/grafana-seapath-alloc.json` into
Grafana (Dashboards → Import).  The dashboard shows:

- **Pool Overview** — free cores, free pairs, active VM/IRQ/claim counts,
  fallback counter, metrics age (all with colour thresholds)
- **CPU Map** — colour-coded per-CPU grid, one cell per logical CPU
  grouped by physical core (green=free, blue=vm, orange=irq,
  teal=quadlet, pink=run, purple=claim, dark red=reserved, gold=slot,
  yellow-orange=irq_slot — a slot whose members include NIC IRQs,
  gray=housekeeping).  The tooltip adapts to the cell: slot cells list
  each member with its scheduler and priority, other cells show the
  actor, thread group, scheduler and priority when set.  The legend
  gutter also displays the slot warnings (a green `none` when the
  colocations are clean) and the soft/hard fallback counters, so the
  map alone gives the full picture.
- **VM Threads** — one row per QEMU thread with VM name, kernel comm,
  CPU(s), scheduler and RT priority
- **NIC IRQs** — interface, IRQ range, CPU
- **Claims** — label, CPU, scheduler, priority, PID
- **Allocation Failures** — rate graph + last-fallback context panel

A cluster-wide variant, `grafana-seapath-alloc-cluster.json`, shows one CPU
map per node (repeated panels, `cluster`/`nodename` template variables).
Its gutter additionally carries the list of VMs running on the node and
a per-node health block (RAM, disk and swap usage, failed systemd units)
with the usual colour thresholds, so the first row only keeps the
cluster-wide indicators (Ceph, Corosync, Pacemaker).

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
| `seapath_alloc_slots` | gauge | Active named shared-core slots |
| `seapath_alloc_slot_members{slot}` | gauge | Actors currently sharing each slot's cores |
| `seapath_alloc_active_fallbacks{severity}` | gauge | Actors **currently** running degraded: `severity=hard` (housekeeping, no RT isolation) or `severity=soft` (exclusive_logical instead of physical, RT preserved); auto-expires when the process exits |
| `seapath_alloc_active_fallback_info{label,group,requested,severity}` | gauge | One series per currently degraded actor (info metric, value=1) |
| `seapath_alloc_allocation_fallbacks_total` | counter | Cumulative degradation events (hard + soft) since last reset |
| `seapath_alloc_last_fallback_timestamp_seconds` | gauge | Timestamp of the most recent degradation event |
| `seapath_alloc_last_fallback_info{label,group,requested,severity}` | gauge | Context of the most recent degradation event (info metric) |
| `seapath_alloc_scrape_timestamp_seconds` | gauge | Timestamp when the timer last wrote the file |

**Detailed per-entity metrics** (for the Grafana CPU map):

| Metric | Type | Description |
|--------|------|-------------|
| `seapath_alloc_cpu_detail{cpu,isolated,ht_pair,ht_sibling,state,slot,member_count,members,label,group,scheduler,priority}` | gauge | One series per CPU — full topology and occupancy context; `state` ∈ `free\|vm\|irq\|claim\|reserved\|slot\|irq_slot\|housekeeping`. A core belonging to a slot always has `state=slot` — or `irq_slot` when the members include NIC IRQs — because a single label/group pair cannot represent several colocated actors: `label` names the slot and `members` summarises the colocated actors with their scheduler/priority — per-member series live in `slot_member_info` |
| `seapath_alloc_vm_thread_info{vm,thread,cpu,scheduler,priority}` | gauge | One series per QEMU thread pinned on isolated cores |
| `seapath_alloc_irq_info{iface,irq_range,cpu}` | gauge | One series per NIC/IRQ group pinned on isolated cores |
| `seapath_alloc_claim_info{label,cpu,scheduler,priority,pid}` | gauge | One series per active claim (container or seapath-run process) |
| `seapath_alloc_slot_member_info{slot,kind,label,group,cpu,scheduler,priority}` | gauge | One series per slot member — the full arbitration picture of each shared core |
| `seapath_alloc_slot_warning_info{slot,reason}` | gauge | One series per risky colocation pattern (see [Shared-core slots](#shared-core-slots-colocation)) |

Fallback state persists across reboots in
`/var/lib/seapath/alloc/fallbacks.json`.

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
            running without RT guarantees. Check /var/log/seapath/alloc.log
            for details.

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
