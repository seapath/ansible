# seapath_alloc: Architecture

## Purpose

seapath-alloc manages a pool of isolated CPU cores (kernel `isolcpus=`) and
assigns them dynamically to QEMU guests, while counting the NIC IRQs and the
other threads already pinned to isolated cores. It complements static
`<cputune>` pinning in libvirt domain XML: a VM with a profile gets its cores
at start and migration time, against the free cores of the host it lands on,
so multiple VMs can share the same cluster nodes without core conflicts. A VM
without a profile keeps whatever its XML says.

---

## Design principles

**No daemon, no allocation database.**
Core occupancy is derived from the kernel at every call: `/proc` affinities of
the threads and `/proc/irq` affinities of the NIC IRQs. A daemon would require
a restart protocol on updates; a database would go stale without a watcher.
Two small state files in `/run` (see below) only record what the kernel cannot
show: claims and reserved HT siblings, both self-healing.

**Serialisation via `flock`.**
Concurrent invocations (two VMs migrating in simultaneously) are serialised by
an exclusive lock on `/run/seapath/alloc/.lock`. No lock manager, no IPC.

**The hook must always exit 0.**
A non-zero exit causes libvirt to abort the VM. Pinning failures are logged
as errors but never interrupt a VM start or migration. The entry point in
`/usr/bin` catches even an import failure of the package.

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
`allocate_cores()` and gets the same strategy and repacking behaviour. Callers
only differ in how they discover threads and register their result.

---

## What makes a core busy

`pool.py` counts an isolated core as busy when:

- a userspace thread is pinned inside the isolated set (its
  `Cpus_allowed_list` is a subset of it), whoever pinned it: a VM pinned by
  this hook, a quadlet with `CPUAffinity=`, a tool started with `taskset`.
  Kernel threads are left out (the per-CPU ones live on every core), except
  the vhost workers that Linux before 6.4 runs as kernel threads for a VM;
- a physical NIC IRQ is routed only to isolated cores (effective affinity
  when the kernel exposes it, requested affinity otherwise). An IRQ on its
  default all-CPUs affinity blocks nothing;
- a live claim holds it (`claims.json`);
- it is the reserved idle sibling of an `exclusive_physical` allocation
  (`.reserved_siblings`).

Only QEMU threads and seapath-run processes are ever moved by the repacker;
every other pinned thread just holds its core.

---

## Data flows

### 1. VM start (libvirt hook)

libvirt runs the hook with `started begin` on a normal start and on the
destination of a live migration.

```
hook.py
  │
  ├─ load_profile(vm_name, domain_xml) ──► config.py
  │    system disk from the domain XML → rbd image-meta get _seapath_alloc
  │    all-none profile if the key is not set; an rbd error is logged as one
  │
  ├─ discover(vm_name) ──► threads.py            ← before the flock
  │    scan /proc/*/cmdline for the QEMU PID
  │    poll /proc/<pid>/task/ until all vCPU TIDs are visible
  │
  ├─ profile asks for no isolated core → apply_all() without the pool
  │
  └─ with CorePool(topo) as pool:                ← acquires flock
        │
        ├─ allocate_cores(pool, specs, topo, pid=...) ──► scheduler.py
        │     │
        │     ├─ (REPACKING) find_repack_moves → repacker.py
        │     │    taskset existing VM threads to free physical pairs
        │     │
        │     ├─ AllocationEngine.allocate(specs) ──► allocator.py
        │     │    pure: free_logical/free_physical snapshot → GroupAllocation list
        │     │
        │     └─ record reserved siblings → pool
        │
        └─ apply_all(threads, allocations) ──► applier.py
              taskset + chrt per TID, order: vCPUs → emulator → vhost → iothreads
              returns the failures, logged as errors by the hook

State written inside flock: .reserved_siblings
```

Discovery runs before the flock because it polls `/proc` for up to a few
seconds and reads no pool state. Application runs inside it: a VM's cores are
not recorded anywhere until `taskset` has run, so releasing the lock before
applying would let a concurrent hook see them as free.

### 2. Container pin (`seapath-container-pin`)

```
claim(label, isolation, scheduler, priority, target_pid) ──► claim.py
  │
  └─ with CorePool(topo) as pool:
        │
        └─ allocate_cores(pool, [spec], topo, pid=main_pid)
              └─ AllocationEngine → scheduler.py

        pool.add_claim(label, cpus, pid, ..., kind="quadlet")
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
the container holds its isolated core through its claim and its pinned
payload threads, and conmon holds none.
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
| `allocations` | `list[GroupAllocation]` | one per spec: `name`, `cpus`, `scheduler`, `priority`, `warning`, `severity` |
| `warnings` | `list[str]` | every non-empty `warning`, prefixed with the group name |
| `reserved_siblings` | `list[[idle, active]]` | idle HT partners of `exclusive_physical` |

`severity` says how far the allocation fell short, and `scheduler.py` logs it
at the matching level:

- `hard` (error): no RT isolation. The group landed on the housekeeping cores
  (pool exhausted) or asked for an unknown isolation. An RT policy is dropped
  to `OTHER`, so that a FIFO thread cannot starve Ceph, corosync and the
  kworkers.
- `soft` (warning): RT isolation preserved with less than asked. An
  `exclusive_physical` group (partly) degraded to `exclusive_logical`, or a
  group with `count` got fewer cores.

---

## Files on the target host

| Path | Written by | Read by |
|------|-----------|---------|
| `/run/seapath/alloc/.lock` | `pool.py` | `pool.py` (flock) |
| `/run/seapath/alloc/claims.json` | `claim.py` | `pool.py` |
| `/run/seapath/alloc/.reserved_siblings` | `pool.py` | `pool.py` |
| `/etc/seapath/alloc.yaml` | Ansible | `config.py` |
| `/var/log/seapath/alloc.log` | all entry points | (operators) |

`/run/` paths are `tmpfs`: they are lost on reboot and rebuilt on first
invocation. The two state files are replaced atomically (temporary file, then
`rename`), so a hook killed mid-write never leaves a truncated file. A claim
records the PID and the start time of its process, and lapses once that
process is gone, even if its PID was reused.

---

## Requirements

- libvirt 10.4.0 or later starts QEMU on the online CPUs minus the isolated
  ones, so a thread left unpinned (`isolation: none`) stays on the
  housekeeping cores. Older libvirt (Debian 12 has 9.0) starts it on every
  online CPU: the scheduler still keeps it off the isolated cores in practice,
  without any guarantee.
- QEMU started with `debug-threads=on` (libvirt always sets it): threads are
  told apart by their names.
- PyYAML (`python3-yaml`) to read the profiles; the role checks for it.

---

## Testing

Unit tests live in `seapath_alloc/tests/`. They use `tmp_path` fixtures to
inject fake `/sys` and `/run/seapath/alloc` trees: no live kernel or libvirt
required.

```bash
cd roles/seapath_alloc/files/seapath_alloc
pip install -e .[test]
pytest tests/ -v
```

From the repository root, `tox -e unit` runs this suite together with the rest
of the repository's Python and measures the whole lot in one report. That is
what the CI runs, and it fails below the `COV_FAIL_UNDER` ratchet in `tox.ini`.
The tests stay inside the package because it is also installable on its own;
`.coveragerc` keeps them out of the coverage denominator.

`conftest.py` provides two fixtures: `sys_path`, a fake `/sys` CPU tree with
the reference topology (12 cores, 0-3 housekeeping, 4-11 isolated, 2-way HT),
and `std_topology`, a `Topology` backed by it. Building a different tree is
what the module-level helpers are for: `make_cpu_topology` (any core count,
isolation set and HT pairing), `make_proc_qemu` (a `/proc/<pid>` tree for a
QEMU process with its vCPU, emulator, vhost and iothread threads),
`make_proc_irq` and `make_sys_nic_irqs` (IRQ affinity and a NIC's MSI-X
interrupts). Fixtures around the pool and its state files are defined in the
test modules that use them.

The role itself has a Molecule scenario (`molecule/default`) that deploys it
in a Debian 13 container and runs the installed hook.
