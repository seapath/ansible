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
