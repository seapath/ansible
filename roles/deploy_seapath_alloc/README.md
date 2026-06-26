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

Pinning is configured per VM via Ceph RBD image metadata:

```bash
rbd image-meta set rbd/<image> _seapath_alloc '
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
   isolation implies RT intent).
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

- Allocates one isolated core via the pool.
- Writes `cpuset.cpus` at every level of the service cgroup tree (including
  Podman's `libpod-payload` sub-cgroup).
- Applies `taskset -cp` and `chrt` per PID.

`seapath-container-unpin <service>` releases the claim.

The service name may be given with or without the `.service` suffix.

### 3. NIC IRQ threads

The `configure_nic_irq_affinity` role deploys a monitor daemon
(`nic-irq-monitor.sh`) that pins NIC MSI-IRQ threads to isolated cores
whenever a managed interface comes up. When `seapath-alloc` is installed, the
daemon calls:

```bash
seapath-alloc suggest --count <queue_count>
```

to obtain free isolated cores at that moment. If `seapath-alloc` is not
installed or returns nothing, it falls back to the static CPU list from
`/etc/nic-irq-affinity.conf`.

`suggest` does not register a claim — it only reports which cores are currently
free. NIC IRQ occupancy is tracked **passively**: the pool reads
`/proc/irq/<n>/smp_affinity_list` on every invocation and treats any isolated
core already pinned by an IRQ as occupied, with no explicit registration step.

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
each one (VM name, container service name, IRQ number, or claim label).

## Log output

The libvirt hook writes to `/var/log/seapath/alloc.log` (rotated weekly via
`/etc/logrotate.d/seapath-alloc`). Container pin/unpin and `seapath-run` write
to stderr (captured by journald when run from a systemd unit).
