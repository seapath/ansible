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
              │
              └─ record reserved siblings → pool
                 record_fallback() on warnings → exporter.py
                                                 (fallbacks.json, active_fallbacks.json)

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

  apply_cpuset + chrt ──► cgroup.py
```

### 3 — Prometheus export (`seapath-alloc export`)

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

`conftest.py` provides the shared fixtures: `cpu_sys_path` (fake `/sys` tree),
`alloc_dir` (fake `/run/seapath/alloc`), and `topo` (a `Topology` instance
backed by the fake tree).
