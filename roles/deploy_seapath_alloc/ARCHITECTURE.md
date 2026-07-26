# deploy_seapath_alloc — Architecture

## Purpose

seapath-alloc manages a pool of isolated CPU cores (kernel `isolcpus=`) and
assigns them dynamically to QEMU guests, containers, NIC IRQ threads, and
third-party processes.  It replaces static `<cputune>` pinning in libvirt
domain XML with per-host dynamic allocation triggered at VM start/migration
time, so multiple VMs can share the same cluster nodes without core conflicts.

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
├── claim.py          claim/release logic for seapath-run processes
└── hook.py           libvirt QEMU hook entry point
│
│  ── observability ──────────────────────────────────────────────────────
├── status.py         pool state collection, no side effects
└── cli.py            entry points for all CLI binaries
```

`scheduler.py` is the single convergence point: every allocation path
(VM hook, container pin, `seapath-run`) calls `allocate_cores()` and gets the
same strategy and repacking behaviour.  Callers only differ in how
they discover threads and register their result.

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
