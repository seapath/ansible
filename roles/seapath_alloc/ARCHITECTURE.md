# seapath_alloc: Architecture

## Purpose

seapath-alloc manages a pool of isolated CPU cores (kernel `isolcpus=`) and
assigns them dynamically to QEMU guests, containers and third-party
processes, while counting the NIC IRQs and the other threads already pinned
to isolated cores. It complements static `<cputune>` pinning in libvirt
domain XML: a VM with a profile gets its cores at start and migration time,
against the free cores of the host it lands on, so multiple VMs can share the
same cluster nodes without core conflicts. A VM without a profile keeps
whatever its XML says. Named shared-core **slots** additionally let several
actors share the same cores, arbitrated by their RT priorities (see
[Shared-core slots](#shared-core-slots--model-and-rationale)).

---

## Design principles

**No daemon, no allocation database.**
Core occupancy is derived from the kernel at every call: `/proc` affinities of
the threads and `/proc/irq` affinities of the NIC IRQs. A daemon would require
a restart protocol on updates; a database would go stale without a watcher.
Two small state files in `/run` (see below) only record what the kernel cannot
show: claims (containers, `seapath-run` processes) and reserved HT siblings,
both self-healing.

**Serialisation via `flock`.**
Concurrent invocations (two VMs migrating in simultaneously, a container pin
racing with a VM start) are serialised by an exclusive lock on
`/run/seapath/alloc/.lock`. No lock manager, no IPC.

**Self-healing claims.**
A claim whose PID no longer appears in `/proc` is dropped silently on the next
pool read — no explicit release protocol needed after a crash or OOM kill.

**Self-healing slots.**
A slot (named shared-core group, `slots.json`) expires once no live actor —
QEMU thread, claim or NIC IRQ — occupies any of its cores. A memberless slot
younger than 60 s is kept: this grace period covers the window between
`seapath-alloc slot` returning and the caller actually pinning (e.g. the IRQ
monitor). Slot cores count as busy for every normal allocation; only specs
referencing the slot by name land on them. Full rationale in
[Shared-core slots](#shared-core-slots--model-and-rationale) below.

**The hook must always exit 0.**
A non-zero exit causes libvirt to abort the VM. Pinning failures are logged
as errors but never interrupt a VM start or migration. The entry point in
`/usr/bin` catches even an import failure of the package.

---

## Shared-core slots — model and rationale

### The problem slots solve

`exclusive_*` isolation means alone on the core. Two consequences: an
actor's RT priority never arbitrates against other actors (it only matters
against the per-CPU kernel threads that remain on isolated cores), and
low-duty actors — an IRQ thread, a TS emulator — each burn a full core.
The original model conflated two orthogonal things in one key: *isolation*
(this core is withdrawn from the pool — a property of a core group) and
*placement* (which actor runs there, under which policy — a property of
each actor). Colocation requires an object between the actor and the core.

### The model

A **slot** is that object: a named group of isolated cores. Specs reference
it by name (`slot: <name>`); the first reference materialises it, later
references land on the same cores. `isolation` and `count` are properties
of the slot; `scheduler`/`priority` remain per member — which is precisely
what makes priority meaningful again: members preempt each other according
to their policies, on the slot's cores.

The pre-slot `count` key (a `vhost`/`iothread` group sharing N cores) is the
same concept minus the name: an *anonymous private slot*, scoped to one
thread group of one VM. It needs no `slots.json` entry — with no possible
joiners, liveness from `/proc` suffices — and both keys compose: a spec with
`slot` + `count` creates a public N-core slot. The allocator reflects this:
slot creation (`_pick_slot`) reuses the exact `count` allocation primitive
(`_pick`).

### Decisions, and why

**Slot creation follows actor mobility.**
*Mobile* actors (VM thread groups, containers, `seapath-run` processes)
migrate between cluster nodes: their cores cannot be decided per-node in
advance — that unpredictability is the reason seapath-alloc exists — so
their slots are allocated from the pool at first reference, through the
normal isolation paths. *Fixed* actors (NIC IRQs: the NIC is physically in
the server, its IRQs exist from boot to shutdown) have no placement problem
to solve at runtime — the operator already decided the core in the
inventory. They never ask the pool; they *declare* their slot on the
operator-chosen core (`declare_slot()`, `seapath-alloc slot NAME --cpus`),
and the pinning itself never depends on seapath-alloc — worst case only the
colocation opportunity is lost. A dynamic "ask the pool" mode for IRQs was
considered and deliberately rejected: an IRQ never exits, so its allocation
would never be released — a static assignment in disguise, less legible
than the inventory, with an availability dependency for no benefit.
The rule generalises: **the fixed actor publishes its position; mobile
actors join it by name — never the reverse.** Apply the same pattern to any
future host-bound actor.

**One host-global namespace, resolved locally.**
The name is the entire coordination mechanism: no per-VM namespacing, no
consent protocol — knowing the name is the handshake. This is what makes
cluster deployments work with zero per-node configuration in the profiles:
`slot: sv0` in a VM's RBD metadata resolves on whichever node the VM lands
on, to *that node's* sv0 (e.g. the core its local NIC declared). The cost
is that a generic name copy-pasted between unrelated profiles colocates
them by accident — a naming-discipline issue, accepted and documented, not
a mechanism issue.

**The creating round fixes the slot's attributes.**
Within one allocation round (one VM profile), every spec referencing the
slot co-defines it: size is the largest `count` requested, isolation the
strongest (`_merge_slot_defs`). This is required because the spec order
inside a profile — vcpus → emulator → vhost, dictated by the apply order —
is an implementation detail the user does not control; "first spec wins"
would make the slot's size depend on which group happens to be expanded
first. Across rounds the slot already exists, and a joiner asking for a
different isolation or count cannot be honoured without moving every other
member — which would break the very guarantee those members signed up
for — so joiners join as-is and the mismatch is logged. Corollary for
operators: across VMs, declare a slot's attributes identically everywhere,
or accept first-round-wins.

**Nothing is ever refused.**
Any spec may reference any slot — including RT vCPUs, where colocation can
stall the guest kernel. Forbidding cases would mean per-type exception code
and paths that must be able to fail, while the hook must always exit 0 and
the operator is the authority on their own machine. Risky-but-allowed
patterns are surfaced instead of blocked: logged, and exported as
`slot_warning_info` (`equal_rt_priority`, `rt_priority_ge_irq`,
`vcpu_shared`). Detection lives in status.py so it is recomputed live and
cannot go stale.

**A housekeeping fallback does not persist the slot.**
A slot that could not get isolated cores has nothing to share: each member
degrades individually (hard fallback, recorded), and the name stays free so
a later reference can still create the slot properly once cores free up.

**Membership is observed, never stored.**
`slots.json` records name/cores/isolation/created only. Who is *in* the
slot is recomputed on demand by intersecting the slot's cores with the same
live actor sources as everything else (`/proc` affinities, claims, IRQ
affinities). Stored membership could go stale; observed membership cannot.
This is also what drives expiry (no live actor on the cores → slot lapses)
and keeps the whole feature consistent with the no-database principle.

**The repacker never moves slot cores.**
Moving one member would break the colocation, and some members (IRQs)
cannot be moved by taskset at all. Slot cores still count as occupied for
pair accounting, and spreading treats them as HT interferers exactly like
NIC IRQs.

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
├── config.py         profile loading (RBD metadata, /etc/seapath/alloc.d)
│                     + /etc/seapath/alloc.yaml settings
├── scheduler.py      single pipeline: strategy + repacking + AllocationEngine
│                     + reserved-sibling registration + fallback recording
│
│  ── application paths (one per caller type) ───────────────────────────
├── threads.py        /proc QEMU PID + TID discovery (VM path only)
├── applier.py        taskset + chrt application (VM path only)
├── cgroup.py         cpusets, per-thread affinity and policy
│                     (container path + repacker)
├── claim.py          claim/release logic for containers and seapath-run
├── hook.py           libvirt QEMU hook entry point
│
│  ── observability ──────────────────────────────────────────────────────
├── status.py         pool state collection, no side effects; shared by
│                     CLI (seapath-alloc status) and Prometheus exporter
├── conformance.py    host RT tuning reader: tuned profile, kernel cmdline,
│                     sched_rt, hugepages, THP, SMT, IRQ affinity, ACPI
├── exporter.py       Prometheus textfile writer + fallback persistence
└── cli.py            entry points for all CLI binaries
```

`scheduler.py` is the single convergence point: every allocation path
(VM hook, container pin, `seapath-run`) calls `allocate_cores()` and gets the
same strategy, repacking, and fallback-recording behaviour. Callers only
differ in how they discover threads and register their result.

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
  │    system disk from the domain XML → rbd image-meta get _seapath_alloc (cluster)
  │    → /etc/seapath/alloc.d/<vm>.yaml                                  (standalone)
  │    all-none profile if neither exists; a read error is logged as one
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
        │     │    specs with slot: join existing slot cores, or create the
        │     │    slot through the normal isolation paths
        │     │
        │     ├─ record reserved siblings + new slots → pool
        │     │
        │     └─ record_fallback() on degradations → exporter.py
        │          (fallbacks.json, active_fallbacks.json)
        │
        └─ apply_all(threads, allocations) ──► applier.py
              taskset + chrt per TID, order: vCPUs → emulator → vhost → iothreads
              returns the failures, logged as errors by the hook

State written inside flock: .reserved_siblings, slots.json
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

The scheduler `APP` skips this step.  It is for a container whose threads
must not share a policy: a real-time engine process next to an agent that has
to stay in SCHED_OTHER, where no lock is shared between the two.  The
application sets each thread's policy itself, and the pin only places the
cores.

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

### 3. Slot declaration for IRQs (`seapath-alloc slot`)

```
cli.py slot <name> --cpus <list>
  │
  └─ with CorePool(topo) as pool:
        └─ declare_slot() ──► scheduler.py
             registers the operator-chosen cores in slots.json
             never fails: conflicts and non-isolated cores are logged

The cores come from the operator (nic-irq-affinity.conf, i.e. the
inventory), not from the pool: the monitor pins the IRQs itself and only
informs seapath-alloc so the cores are protected from normal allocations
and joiners can reference the slot by name. The 60 s memberless grace in
pool._live_slots() covers the window until the IRQs are pinned, after which
they keep the slot alive through the passive /proc/irq source.
```

### 4. Prometheus export (`seapath-alloc export`)

```
exporter.generate()
  │
  ├─ status.collect() ──► pool.py (flock) + topology.py
  │    reads /proc, /sys, claims.json, .reserved_siblings
  │    returns structured dict (actors, free_logical, free_physical, ...)
  │
  ├─ _load_state()   → fallbacks.json     (cumulative counter)
  ├─ _load_active()  → active_fallbacks.json
  │    expire entries where /proc/{pid} no longer exists
  │    expose seapath_alloc_active_fallbacks{severity} gauges
  │
  └─ conformance.collect(isolated=topo.isolated_cpus())
       reads /etc/tuned, /proc/cmdline, the sched_rt sysctls, the hugepage
       pools, /sys THP and SMT, /proc/irq affinities, /sys/firmware/acpi
       exposes the seapath_rt_* families

  write .prom via atomic rename → /var/lib/prometheus/node_exporter/seapath-alloc.prom
```

The second half is what the node's tuning *is*, beside what its cores are
*doing*. It lives here because the timer, the atomic write and the
node_exporter textfile directory already exist, and because the two halves are
read together by whoever asks whether a cluster still matches its inventory.
The isolated set is passed in rather than read again: a second reading could
only disagree with the topology the same run already has.

`conformance.py` reports and never judges. What a value ought to be depends on
the machine's inventory, which this collector does not have and must not guess.

---

## Allocation result anatomy

`AllocationEngine.allocate()` returns an `AllocationResult`:

| Field | Type | Content |
|-------|------|---------|
| `allocations` | `list[GroupAllocation]` | one per spec: `name`, `cpus`, `scheduler`, `priority`, `warning`, `severity` |
| `warnings` | `list[str]` | every non-empty `warning`, prefixed with the group name |
| `reserved_siblings` | `list[[idle, active]]` | idle HT partners of `exclusive_physical` |
| `new_slots` | `list[(name, cores, isolation)]` | slots created during this round, written back via `pool.add_slot()`; joins of existing slots produce nothing here |

`severity` says how far the allocation fell short, and `scheduler.py` logs it
at the matching level:

- `hard` (error): no RT isolation. The group landed on the housekeeping cores
  (pool exhausted) or asked for an unknown isolation. An RT policy is dropped
  to `OTHER`, so that a FIFO thread cannot starve Ceph, corosync and the
  kworkers.
- `soft` (warning): RT isolation preserved with less than asked. An
  `exclusive_physical` group (partly) degraded to `exclusive_logical`, or a
  group with `count` got fewer cores.

Both are recorded by `record_fallback(..., severity=...)` for the exporter.
Fallback tracking in `active_fallbacks.json` is PID-keyed so entries
auto-expire when the process exits, without any cleanup step.

---

## Files on the target host

| Path | Written by | Read by |
|------|-----------|---------|
| `/run/seapath/alloc/.lock` | `pool.py` | `pool.py` (flock) |
| `/run/seapath/alloc/claims.json` | `claim.py` | `pool.py` |
| `/run/seapath/alloc/.reserved_siblings` | `pool.py` | `pool.py` |
| `/run/seapath/alloc/slots.json` | `pool.py` | `pool.py` |
| `/var/lib/seapath/alloc/fallbacks.json` | `exporter.py` | `exporter.py` |
| `/var/lib/seapath/alloc/active_fallbacks.json` | `exporter.py` | `exporter.py` |
| `/var/lib/prometheus/node_exporter/seapath-alloc.prom` | `exporter.py` | node_exporter |
| `/etc/seapath/alloc.yaml` | Ansible | `config.py` |
| `/var/log/seapath/alloc.log` | all entry points | (operators) |

`/run/` paths are `tmpfs`: they are lost on reboot and rebuilt on first
invocation. The two state files are replaced atomically (temporary file, then
`rename`), so a hook killed mid-write never leaves a truncated file. A claim
records the PID and the start time of its process, and lapses once that
process is gone, even if its PID was reused. `/var/lib/` paths survive
reboots (cumulative counters, active-fallback tracking).

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

The five entry points installed in `/usr/bin` (`seapath-alloc`,
`seapath-qemu-hook`, `seapath-run`, `seapath-container-pin`,
`seapath-container-unpin`) sit outside the package, so their tests live with
the repository's other script tests, in `tests/test_seapath_run.py`,
`tests/test_seapath_container_pin.py`, `tests/test_seapath_container_unpin.py`
and `tests/test_seapath_entrypoints.py`.

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
