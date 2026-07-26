# seapath_alloc — Architecture

## Purpose

seapath-alloc manages a pool of isolated CPU cores (kernel `isolcpus=`) and
assigns them dynamically to QEMU guests, while counting the NIC IRQs already
pinned to isolated cores.  It replaces static `<cputune>` pinning in libvirt
domain XML with per-host dynamic allocation triggered at VM start/migration
time, so multiple VMs can share the same cluster nodes without core conflicts.

---

## Design principles

**No daemon, no persistent allocation database.**
State is derived from the kernel at every call: `/proc` affinities for VMs and
IRQ threads.  A daemon would require a restart protocol on updates; a database would go stale
without a watcher.  The kernel is always the source of truth.

**Serialisation via `flock`.**
Concurrent invocations (two VMs migrating in simultaneously) are serialised by an exclusive lock on
`/run/seapath/alloc/.lock`.  No lock manager, no IPC.

**The hook must always exit 0.**
A non-zero exit causes libvirt to abort the VM.  Pinning failures are logged
as errors but never interrupt a VM start or migration.

---

## Module structure and layering

```
seapath_alloc/
│
│  ── infrastructure (no allocation logic) ──────────────────────────────
├── topology.py       /sys reader: isolated CPUs, online CPUs, HT pairs
├── pool.py           live kernel-derived occupancy + flock serialisation
├── logging_setup.py  configures file logger → /var/log/seapath/alloc.log
│
│  ── allocation engine (pure: no I/O, no side effects) ─────────────────
├── allocator.py      maps free-core snapshot + specs → concrete assignments
├── repacker.py       thread-migration helpers for the REPACKING strategy
│
│  ── orchestration ──────────────────────────────────────────────────────
├── config.py         RBD metadata + /etc/seapath/alloc.yaml loading
├── scheduler.py      single pipeline: strategy + repacking + AllocationEngine
│                     + reserved-sibling registration
│
│  ── application paths (one per caller type) ───────────────────────────
├── threads.py        /proc QEMU PID + TID discovery (VM path only)
├── applier.py        taskset + chrt application (VM path only)
├── cgroup.py         cpusets, per-thread affinity and policy
│                     (container path + repacker)
├── claim.py          claim/release logic for containers and seapath-run
└── hook.py           libvirt QEMU hook entry point
│
│  ── observability ──────────────────────────────────────────────────────
├── status.py         pool state collection, no side effects
└── cli.py            entry points for all CLI binaries
```

`scheduler.py` is the single convergence point: every allocation path calls
`allocate_cores()` and gets the same strategy and repacking behaviour.  Callers
only differ in how they discover threads and register their result.

---

## Data flows

### 1 — VM start (libvirt hook)

```
hook.py
  │
  ├─ load_profile(vm_name) ──► config.py
  │    virsh domblklist → rbd image-meta get _seapath_alloc
  │    falls back to all-none profile if no metadata
  │
  └─ with CorePool(topo) as pool:          ← acquires flock
        │
        ├─ discover(vm_name) ──► threads.py
        │    scan /proc/*/cmdline for QEMU PID
        │    poll /proc/<pid>/task/ until all vCPU TIDs visible
        │
        └─ allocate_cores(pool, specs, topo, pid=...) ──► scheduler.py
              │
              ├─ (REPACKING) find_repack_moves → repacker.py
              │    taskset existing VM threads to free physical pairs
              │
              ├─ AllocationEngine.allocate(specs) ──► allocator.py
              │    pure: free_logical/free_physical snapshot → Allocation list
              │
              └─ record reserved siblings → pool

  apply_all(threads, allocations) ──► applier.py     ← outside flock window
        taskset + chrt per TID, order: vCPUs → emulator → vhost → iothreads

State written inside flock: .reserved_siblings
```

### 2 — Container pin (`seapath-container-pin`)

```
claim(label, isolation, scheduler, priority, target_pid) ──► claim.py
  │
  └─ with CorePool(topo) as pool:
        │
        └─ allocate_cores(pool, [spec], topo, pid=main_pid, kind="quadlet")
              └─ AllocationEngine → scheduler.py

        pool.add_claim(label, cpus, pid, ...)
        write claims.json

  place_service + schedule_payload ──► cgroup.py     ← outside flock window
        cpuset.cpus per sub-cgroup, sched_setaffinity per thread
        sched_setscheduler per payload thread (cgroup.threads)
```

The claim is owned by the service's `MainPID`. For a quadlet that is conmon,
which lives exactly as long as the container, so the claim expires with it.

**What gets what.**  quadlet generates `podman run --cgroups=split`, which
splits the service cgroup in three: systemd's `.control/` (ExecStartPost=
and friends), conmon's `runtime/`, and the container's `libpod-payload-<id>/`.
Members of a quadlet pod keep their own service and the same layout.

| Cgroup | `cpuset.cpus` | Threads' affinity | Scheduling policy |
|--------|---------------|-------------------|-------------------|
| service root (no process) | allocated + housekeeping | n/a | n/a |
| `libpod-payload-*` and below | allocated | allocated | requested |
| `runtime/`, `.control/` | housekeeping | housekeeping | untouched (SCHED_OTHER) |

A service without a `libpod-payload-*` sub-cgroup (not podman, or another
`--cgroups` mode) is taken as a whole: every level and every thread gets the
allocated cores and the requested policy.

**Per thread.**  `sched_setscheduler` and `sched_setaffinity` act on the one
thread they name.  The threads already running when ExecStartPost= fires (an
interpreter's helper threads, a JVM, a Go or Rust runtime pool) would
otherwise keep SCHED_OTHER next to a SCHED_FIFO main thread on the same
isolated core.  As soon as such a thread holds a lock the FIFO thread needs
(the Python GIL, measured on a protection relay: trip time 15 ms, then
22-27 ms with jitter), the FIFO thread waits for a thread that only runs when
the FIFO thread blocks.  So the policy is applied to each TID listed in
`cgroup.threads`, re-read until no new thread shows up (a thread created by a
sibling not yet switched inherits SCHED_OTHER).  Threads created later
inherit from their creator, which by then has the policy.  A thread vanishing
between the read and the call is skipped, any other refusal is logged, and
the pin carries on: a failing ExecStartPost= would fail the service.

**conmon goes to the housekeeping cores.**  conmon wakes on every write the
container makes to stdout/stderr.  With the workload's policy on the
isolated core, it competes with the workload at equal priority.  In
SCHED_OTHER on that core, it would still run there whenever the workload
blocks and pollute its cache, and a busy workload could starve it and then
block on a full log pipe.  So the isolated core carries the payload only.
In cgroup v2 a child's effective CPUs are bounded by its parent's, hence the
service root spanning both sets while holding no process.  `isolcpus` is not
affected: nothing runs on the root's union, and a non-partition cpuset
creates no scheduling domain.  Pool accounting is not affected either:
quadlet occupancy comes from `claims.json` (`pinned_quadlet_cpus`) only.
The same split keeps the pin and unpin scripts themselves (in `.control/`)
off the isolated core.

**Moving a container.**  The repacker's `CgroupMove` goes through the same
`place_service()`, so a repack keeps the split.  The root is widened to
old + new before the payload is rewritten, and narrowed after: a payload
asking for a CPU its parent lacks falls back to the parent's whole set,
housekeeping included.  A move leaves policies alone, as a `ThreadMove`
does.

## Allocation result anatomy

`AllocationEngine.allocate()` returns an `AllocationResult`:

| Field | Type | Content |
|-------|------|---------|
| `allocations` | `list[Allocation]` | one per spec: `name`, `cpus`, `warning` |
| `reserved_siblings` | `list[(idle, active)]` | idle HT partners of `exclusive_physical` |

`scheduler.py` inspects `alloc.warning` to determine fallback severity:

- `"housekeeping"` in warning → **hard** fallback: no RT isolation, actor runs on shared cores
- any other non-empty warning → **soft** fallback: `exclusive_physical` degraded to `exclusive_logical`, RT isolation preserved

---

## Files on the target host

| Path | Written by | Read by |
|------|-----------|---------|
| `/run/seapath/alloc/.lock` | `pool.py` | `pool.py` (flock) |
| `/run/seapath/alloc/claims.json` | `claim.py` | `pool.py` |
| `/run/seapath/alloc/.reserved_siblings` | `pool.py` | `pool.py` |
| `/etc/seapath/alloc.yaml` | Ansible | `config.py` |
| `/var/log/seapath/alloc.log` | all entry points | — |

`/run/` paths are `tmpfs` — they are lost on reboot and rebuilt on first
invocation.

---

## Testing

Unit tests live in `seapath_alloc/tests/`.  They use `tmp_path` fixtures to
inject fake `/sys` and `/run/seapath/alloc` trees — no live kernel or libvirt
required.

```bash
cd roles/seapath_alloc/files/seapath_alloc
pip install -e .[test]
pytest tests/ -v
```

From the repository root, `tox -e unit` runs this suite together with the rest
of the repository's Python and measures the whole lot in one report.  That is
what the CI runs, and it fails below the `COV_FAIL_UNDER` ratchet in `tox.ini`.
The tests stay inside the package because it is also installable on its own;
`.coveragerc` keeps them out of the coverage denominator.

`conftest.py` provides two fixtures: `sys_path`, a fake `/sys` CPU tree with
the reference topology (12 cores, 0-3 housekeeping, 4-11 isolated, 2-way HT),
and `std_topology`, a `Topology` backed by it.  Building a different tree is
what the module-level helpers are for: `make_cpu_topology` (any core count,
isolation set and HT pairing), `make_proc_qemu` (a `/proc/<pid>` tree for a
QEMU process with its vCPU, emulator and vhost threads), `make_proc_irq` and
`make_sys_nic_irqs` (IRQ affinity and a NIC's MSI-X interrupts).  Fixtures
around the pool and its state files are defined in the test modules that use
them.
