# deploy_seapath_alloc — Architecture

## Purpose

seapath-alloc manages a pool of isolated CPU cores (kernel `isolcpus=`) and
assigns them dynamically to QEMU guests, containers, NIC IRQ threads, and
third-party processes.  It replaces static `<cputune>` pinning in libvirt
domain XML with per-host dynamic allocation triggered at VM start/migration
time, so multiple VMs can share the same cluster nodes without core conflicts.
Named shared-core **slots** additionally let several actors share the same
cores, arbitrated by their RT priorities (see
[Shared-core slots](#shared-core-slots--model-and-rationale)).

---

## Design principles

**No daemon, no persistent allocation database.**
State is derived from the kernel at every call: `/proc` affinities for VMs and
IRQ threads, `claims.json` for containers and `seapath-run` processes.  A
daemon would require a restart protocol on updates; a database would go stale
without a watcher.  The kernel is always the source of truth.

**Serialisation via `flock`.**
Concurrent invocations (two VMs migrating in simultaneously, a container pin
racing with a VM start) are serialised by an exclusive lock on
`/run/seapath/alloc/.lock`.  No lock manager, no IPC.

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
A non-zero exit causes libvirt to abort the VM.  Pinning failures are logged
as errors but never interrupt a VM start or migration.

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
├── config.py         RBD metadata + /etc/seapath/alloc.yaml loading
├── scheduler.py      single pipeline: strategy + repacking + AllocationEngine
│                     + reserved-sibling registration + fallback recording
│
│  ── application paths (one per caller type) ───────────────────────────
├── threads.py        /proc QEMU PID + TID discovery (VM path only)
├── applier.py        taskset + chrt application (VM path only)
├── cgroup.py         cgroup helpers (container path + repacker)
├── claim.py          claim/release logic for containers and seapath-run
├── hook.py           libvirt QEMU hook entry point
│
│  ── observability ──────────────────────────────────────────────────────
├── status.py         pool state collection, no side effects; shared by
│                     CLI (seapath-alloc status) and Prometheus exporter
├── exporter.py       Prometheus textfile writer + fallback persistence
└── cli.py            entry points for all CLI binaries
```

`scheduler.py` is the single convergence point: every allocation path
(VM hook, container pin, `seapath-run`) calls `allocate_cores()` and gets the
same strategy, repacking, and fallback-recording behaviour.  Callers only
differ in how they discover threads and register their result.

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
              │    specs with slot: join existing slot cores, or create the
              │    slot through the normal isolation paths
              │
              └─ record reserved siblings + new slots → pool
                 record_fallback() on warnings → exporter.py
                                                 (fallbacks.json, active_fallbacks.json)

  apply_all(threads, allocations) ──► applier.py     ← outside flock window
        taskset + chrt per TID, order: vCPUs → emulator → vhost → iothreads

State written inside flock: .reserved_siblings, slots.json
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

  apply_cpuset + chrt ──► cgroup.py
```

### 3 — Slot declaration for IRQs (`seapath-alloc slot`)

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

### 4 — Prometheus export (`seapath-alloc export`)

```
exporter.generate()
  │
  ├─ status.collect() ──► pool.py (flock) + topology.py
  │    reads /proc, /sys, claims.json, .reserved_siblings
  │    returns structured dict (actors, free_logical, free_physical, ...)
  │
  ├─ _load_state()   → fallbacks.json     (cumulative counter)
  └─ _load_active()  → active_fallbacks.json
        expire entries where /proc/{pid} no longer exists
        expose seapath_alloc_active_fallbacks{severity} gauges

  write .prom via atomic rename → /var/lib/prometheus/node_exporter/seapath-alloc.prom
```

---

## Allocation result anatomy

`AllocationEngine.allocate()` returns an `AllocationResult`:

| Field | Type | Content |
|-------|------|---------|
| `allocations` | `list[Allocation]` | one per spec: `name`, `cpus`, `warning` |
| `reserved_siblings` | `list[(idle, active)]` | idle HT partners of `exclusive_physical` |
| `new_slots` | `list[(name, cores, isolation)]` | slots created during this round, written back via `pool.add_slot()`; joins of existing slots produce nothing here |

`scheduler.py` inspects `alloc.warning` to determine fallback severity:

- `"housekeeping"` in warning → **hard** fallback: no RT isolation, actor runs on shared cores; `record_fallback(..., severity="hard")`
- any other non-empty warning → **soft** fallback: `exclusive_physical` degraded to `exclusive_logical`, RT isolation preserved; `record_fallback(..., severity="soft")`

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
| `/var/log/seapath/alloc.log` | all entry points | — |

`/run/` paths are `tmpfs` — they are lost on reboot and rebuilt on first
invocation.  `/var/lib/` paths survive reboots (cumulative counters,
active-fallback tracking).

---

## Testing

Unit tests live in `seapath_alloc/tests/`.  They use `tmp_path` fixtures to
inject fake `/sys` and `/run/seapath/alloc` trees — no live kernel or libvirt
required.

```bash
cd roles/deploy_seapath_alloc/files/seapath_alloc
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
