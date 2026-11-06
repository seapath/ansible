# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Live view of isolated CPU core occupancy on the local node.

Core occupancy is derived from the kernel at call time:

  /proc/<pid>/task/<tid>/status   Cpus_allowed_list of every thread
  /proc/irq/*/effective_affinity_list (or smp_affinity_list)  NIC IRQs

An isolated core is busy when a userspace thread is pinned inside the
isolated set (whoever pinned it: this tool, a quadlet's CPUAffinity=, a
taskset), when a vhost worker of a VM is, when a physical NIC IRQ is routed
only to isolated cores, or when a claim or a reserved HT sibling holds it.

Three small files complete that picture, all in /run (tmpfs, gone at
reboot):

  claims.json          cores held by a container or a seapath-run process
  .reserved_siblings   the idle HT sibling of each exclusive_physical
                       allocation
  slots.json           named shared-core slots

They heal themselves on read: a claim lapses when its process is gone (PID
and start time no longer match), a reserved sibling when the core it guards
is no longer held by a pinned thread, a live claim or a slot, and a slot
once no live actor (pinned thread, claim, NIC IRQ) occupies its cores.

All reads and writes happen under a flock on .lock so concurrent hook
invocations (two VMs starting simultaneously) see a consistent snapshot and
don't double-allocate the same core.
"""

import fcntl
import glob
import json
import logging
import os
import re
import time

from .topology import Topology, parse_cpu_list

log = logging.getLogger(__name__)

_DEFAULT_ALLOC_DIR = "/run/seapath/alloc"

# A memberless slot younger than this is kept: it covers the window between
# slot creation and the moment its first member becomes visible to the pool
# (e.g. `seapath-alloc slot` returns before the IRQ is pinned).
_SLOT_GRACE_SECONDS = 60


def _boot_seconds() -> int:
    """
    Seconds since boot. Slot ages use this clock: a wall clock jump (NTP or
    PTP stepping the time, a master stuck in 1970) would otherwise keep a
    slot in grace forever or end the grace early. slots.json lives in /run,
    which starts empty at every boot, so the clock never goes back on it.
    """
    clock = getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC)
    return int(time.clock_gettime(clock))

# Flag of a kernel thread in the ninth field of /proc/<pid>/stat.
_PF_KTHREAD = 0x00200000

_VCPU_RE = re.compile(r'^CPU (\d+)/KVM$')
# QEMU names an iothread "IO <object id>" and libvirt gives them the ids
# iothread1, iothread2, ... QEMU's own monitor iothread is "IO mon_iothread"
# and is no workload of ours.
_IOTHREAD_RE = re.compile(r'^IO iothread(\d+)$')
# vhost workers are named after the QEMU PID: user threads of QEMU from
# Linux 6.4, kernel threads of their own before.
_VHOST_RE = re.compile(r'^vhost-(\d+)$')


def _is_qemu_comm(comm: str) -> bool:
    """True if the thread name belongs to a QEMU workload thread."""
    return (
        comm.startswith('qemu-system')
        or comm == 'qemu-kvm'
        or bool(_VCPU_RE.match(comm))
        or bool(_VHOST_RE.match(comm))
        or bool(_IOTHREAD_RE.match(comm))
    )


def _read_stat(path: str):
    """Return (flags, start_time) from a /proc stat file, or None."""
    try:
        with open(path) as f:
            data = f.read()
    except OSError:
        return None
    # The comm field is in parentheses and may itself hold spaces or
    # parentheses: the fields that follow start after the last ")".
    fields = data[data.rfind(')') + 1:].split()
    try:
        return int(fields[6]), int(fields[19])
    except (IndexError, ValueError):
        return None


def process_start_time(pid: int, proc_path: str = "/proc"):
    """Start time of pid in clock ticks since boot, or None."""
    stat = _read_stat(os.path.join(proc_path, str(pid), "stat"))
    return stat[1] if stat else None


class CorePool:

    def __init__(self, topology: Topology = None,
                 alloc_dir: str = _DEFAULT_ALLOC_DIR,
                 proc_path: str = "/proc",
                 sys_path: str = "/sys"):
        self._topo = topology or Topology()
        self._alloc_dir = alloc_dir
        self._proc = proc_path
        self._sys = sys_path
        self._lock_fd = None
        self._lock_depth = 0

        self._lock_file = os.path.join(alloc_dir, ".lock")
        self._reserved_file = os.path.join(alloc_dir, ".reserved_siblings")
        self._claims_file = os.path.join(alloc_dir, "claims.json")
        self._slots_file = os.path.join(alloc_dir, "slots.json")

        # Memoized scans, computed once and invalidated by bust_cache().
        self._busy_cache = None
        self._threads_cache = None
        self._irq_cache = None
        self._claims_cache = None
        self._slots_cache = None
        # PIDs whose /proc threads are ignored in busy accounting.
        # Set via exclude_pids() before the first free_logical()/free_physical()
        # call to allow re-allocating a running VM onto its own current CPUs.
        self._excluded_pids: set = set()

    # ------------------------------------------------------------------ locking

    def lock(self):
        """
        Acquire the exclusive flock. Call before any read or write.

        A flock belongs to the open file description, so taking it again
        from the same process through a second open() would block forever.
        Nested calls on the same pool only count the depth instead.
        """
        if self._lock_depth:
            self._lock_depth += 1
            return
        os.makedirs(self._alloc_dir, exist_ok=True)
        fd = open(self._lock_file, 'w')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except BaseException:
            fd.close()
            raise
        self._lock_fd = fd
        self._lock_depth = 1
        log.debug("flock acquired")

    def unlock(self):
        if not self._lock_depth:
            return
        self._lock_depth -= 1
        if self._lock_depth:
            return
        fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        self._lock_fd.close()
        self._lock_fd = None
        log.debug("flock released")

    def __enter__(self):
        self.lock()
        return self

    def __exit__(self, *_):
        self.unlock()

    # ------------------------------------------------------------------ public

    def topology(self) -> Topology:
        return self._topo

    def free_logical(self) -> list:
        """Isolated cores not currently occupied by any actor."""
        busy = self._busy_cpus()
        return [c for c in self._topo.isolated_cpus() if c not in busy]

    def free_physical(self) -> list:
        """
        Lower siblings of fully-free isolated physical pairs.

        exclusive_physical allocations pin the thread to the lower sibling and
        leave the upper sibling idle. We only offer lower siblings here so the
        allocator always pins to a predictable member of the pair.
        """
        busy = self._busy_cpus()
        free = []
        for pair in self._topo.isolated_sibling_pairs():
            if not pair & busy:
                free.append(min(pair))
        return sorted(free)

    def irq_cpus(self) -> set:
        """Isolated cores that a physical NIC IRQ is routed to."""
        if self._irq_cache is None:
            self._irq_cache = self._busy_by_irqs(set(self._topo.isolated_cpus()))
        return self._irq_cache

    def occupied_cpus(self) -> set:
        """Isolated cores held by a pinned thread or a live claim."""
        isolated = set(self._topo.isolated_cpus())
        return self._busy_by_threads(isolated) | self._busy_by_claims(isolated)

    def add_reserved_sibling(self, idle_cpu: int, active_cpu: int):
        """
        Record that idle_cpu is the idle HT sibling of an exclusive_physical
        allocation whose thread is pinned to active_cpu.

        The reservation expires automatically when active_cpu is no longer
        held (VM died), so no explicit release is needed.
        """
        entries = self._load_reserved_siblings()
        entries.append([idle_cpu, active_cpu])
        self._save_reserved_siblings(entries)
        self.bust_cache()

    def add_claim(self, label: str, pid: int, cores: list,
                  scheduler: str = "OTHER", priority: int = 0,
                  kind: str = "", slot: str = ""):
        """
        Register a claim from a container or operator tool.

        The process start time is stored next to the PID so that a recycled
        PID does not keep a dead claim alive. A claim without a PID never
        lapses on its own: it stays until remove_claim().
        """
        claims = self._load_claims()
        claims = [c for c in claims if c.get("label") != label]
        entry = {
            "label": label,
            "pid": pid,
            "cores": list(cores),
            "scheduler": scheduler,
            "priority": priority,
        }
        start = process_start_time(pid, self._proc) if pid else None
        if start is not None:
            entry["start"] = start
        if kind:
            entry["kind"] = kind
        if slot:
            entry["slot"] = slot
        claims.append(entry)
        self._save_claims(claims)
        self.bust_cache()

    def move_claim_cpu(self, label: str, new_cpu: int):
        """Update the CPU assignment for an existing claim after a repacker move."""
        claims = self._load_claims()
        for c in claims:
            if c.get("label") == label:
                c["cores"] = [new_cpu]
                break
        self._save_claims(claims)
        self.bust_cache()

    def remove_claim(self, label: str):
        claims = self._load_claims()
        claims = [c for c in claims if c.get("label") != label]
        self._save_claims(claims)
        self.bust_cache()

    def all_claims(self) -> list:
        """Return active (non-expired) claims."""
        return self._live_claims()

    def add_slot(self, name: str, cores: list, isolation: str):
        """
        Register a named shared-core slot.

        A slot's cores are counted busy for every normal allocation; actors
        that reference the slot by name share them instead of consuming new
        cores. The slot expires automatically once no live actor occupies any
        of its cores (see _live_slots).
        """
        slots = self._load_slots()
        slots = [s for s in slots if s.get("name") != name]
        slots.append({
            "name": name,
            "cores": list(cores),
            "isolation": isolation,
            "created": _boot_seconds(),
        })
        self._save_slots(slots)
        self.bust_cache()

    def slots(self) -> list:
        """Return active (non-expired) slots."""
        return self._live_slots()

    def slot_cores(self) -> set:
        """All cores belonging to any active slot."""
        cores = set()
        for slot in self._live_slots():
            cores.update(slot.get("cores", []))
        return cores

    def active_reserved_siblings(self) -> list:
        """
        Return [(idle_cpu, active_cpu), ...] for live exclusive_physical reservations.

        Only entries whose active_cpu is still occupied by a live actor (pinned
        thread, active claim or slot) are returned; stale entries are
        discarded.
        """
        entries = self._load_reserved_siblings()
        currently_pinned = self.occupied_cpus() | self.slot_cores()
        return [(idle, active) for idle, active in entries
                if active in currently_pinned]

    # ------------------------------------------------------------------ discovery

    def _busy_cpus(self) -> set:
        if self._busy_cache is not None:
            return self._busy_cache
        occupied = self.occupied_cpus()
        slot_cores = self.slot_cores()
        busy = set(occupied) | slot_cores
        busy.update(self.irq_cpus())
        # A slot whose only members are IRQs keeps its reservation too.
        busy.update(self._busy_reserved_siblings(occupied | slot_cores))
        self._busy_cache = busy & set(self._topo.isolated_cpus())
        return self._busy_cache

    def exclude_pids(self, pids: set):
        """
        Exclude threads of these QEMU process PIDs from busy-CPU accounting.

        When re-allocating a running VM (hook "started begin" fired on a VM
        that is already up), the VM's threads are still pinned to their old
        CPUs in /proc.  Excluding the QEMU PID lets the pool see those CPUs
        as available so the hook can assign a fresh, optimal allocation.

        The VM's reserved siblings then look lapsed too and are freed for this
        allocation, in memory only: the file keeps them, so a re-allocation
        that fails does not hand the running VM's idle sibling to someone else.

        Must be called before the first free_logical() / free_physical() call
        while the pool lock is held.
        """
        self._excluded_pids = pids
        self.bust_cache()

    def bust_cache(self):
        self._busy_cache = None
        self._threads_cache = None
        self._irq_cache = None
        self._claims_cache = None
        self._slots_cache = None

    def _thread_excluded(self, parts: list, comm: str) -> bool:
        """
        True when a /proc thread belongs to an excluded QEMU PID.

        Matches both the QEMU process's own threads (path PID) and its vhost
        kernel threads, which live under their own PID but encode the QEMU
        PID in their comm ("vhost-<qemu_pid>").
        """
        if not self._excluded_pids:
            return False
        try:
            if int(parts[-4]) in self._excluded_pids:
                return True
        except (ValueError, IndexError):
            pass
        m = _VHOST_RE.match(comm)
        return bool(m) and int(m.group(1)) in self._excluded_pids

    def _pinned_threads(self) -> list:
        """
        Threads pinned inside the isolated set, scanned once per snapshot.

        A thread is pinned when its Cpus_allowed_list is a subset of the
        isolated set: with isolcpus= nothing lands there by default. Kernel
        threads are left out (the per-CPU ones, ksoftirqd, kworkers, are
        bound to every core by design), except the vhost workers that Linux
        before 6.4 runs as kernel threads on behalf of a VM.

        Returns a list of dicts: tid, tgid, ppid, comm, cpus.
        """
        if self._threads_cache is not None:
            return self._threads_cache
        isolated = set(self._topo.isolated_cpus())
        result = []
        pattern = os.path.join(self._proc, "*/task/*/status")
        for status_path in glob.glob(pattern):
            parts = status_path.split(os.sep)
            try:
                with open(status_path) as f:
                    content = f.read()
            except OSError:
                continue
            name_m = re.search(r'^Name:\s+(.+)', content, re.M)
            allowed_m = re.search(r'^Cpus_allowed_list:\s+(\S+)', content, re.M)
            if not name_m or not allowed_m:
                continue
            allowed = set(parse_cpu_list(allowed_m.group(1)))
            if not allowed or not allowed.issubset(isolated):
                continue
            comm = name_m.group(1).strip()
            if self._thread_excluded(parts, comm):
                continue
            if not _is_qemu_comm(comm):
                stat = _read_stat(os.path.join(os.path.dirname(status_path), "stat"))
                if stat is None or stat[0] & _PF_KTHREAD:
                    continue
            try:
                tid = int(parts[-2])
            except (ValueError, IndexError):
                continue
            tgid_m = re.search(r'^Tgid:\s+(\d+)', content, re.M)
            ppid_m = re.search(r'^PPid:\s+(\d+)', content, re.M)
            result.append({
                "tid": tid,
                "tgid": int(tgid_m.group(1)) if tgid_m else 0,
                "ppid": int(ppid_m.group(1)) if ppid_m else 0,
                "comm": comm,
                "cpus": allowed,
            })
        self._threads_cache = result
        return result

    def _busy_by_threads(self, isolated: set) -> set:
        """Isolated cores held by pinned threads (see _pinned_threads)."""
        busy = set()
        for thread in self._pinned_threads():
            busy.update(thread["cpus"])
        return busy & isolated

    def pinned_workload_threads(self) -> dict:
        """
        Return {cpu: [tid, ...]} for workload threads exclusively pinned to a
        single isolated CPU.  Used by the repacker to enumerate moveable threads.

        Covers QEMU threads (VMs) and seapath-run processes (claim kind="run")
        including their direct children, which inherit the affinity at exec time.
        Quadlet containers are excluded here: they are moved via cgroup cpuset
        and enumerated by pinned_quadlet_cpus() instead. Any other pinned
        thread counts as busy but is never moved.

        Only threads with a single-CPU affinity mask within the isolated set are
        included: multi-CPU affinities are ignored because the repacker cannot
        move threads that span pairs.
        """
        run_pids = {
            c["pid"] for c in self._live_claims()
            if c.get("kind") == "run" and c.get("pid")
        }

        result: dict = {}
        for thread in self._pinned_threads():
            if len(thread["cpus"]) != 1:
                continue
            is_run = thread["tgid"] in run_pids or thread["ppid"] in run_pids
            if not _is_qemu_comm(thread["comm"]) and not is_run:
                continue
            cpu = next(iter(thread["cpus"]))
            result.setdefault(cpu, []).append(thread["tid"])
        return result

    def pinned_quadlet_cpus(self) -> dict:
        """
        Return {cpu: (label, service)} for quadlet claims pinned to a single
        isolated CPU.  Used by the repacker to generate CgroupMove instances.
        """
        isolated = set(self._topo.isolated_cpus())
        result = {}
        for c in self._live_claims():
            if c.get("kind") != "quadlet":
                continue
            cores = [cpu for cpu in c.get("cores", []) if cpu in isolated]
            if len(cores) == 1:
                label = c["label"]
                result[cores[0]] = (label, f"{label}.service")
        return result

    def _busy_by_irqs(self, isolated: set) -> set:
        """
        Isolated cores that physical NIC MSI IRQs are routed to.

        Only IRQs that belong to a physical NIC are counted, enumerated from
        /sys/class/net/*/device/msi_irqs/. This deliberately excludes
        kernel-managed MSI IRQs (e.g. NVMe, xHCI) that the driver subsystem
        routes to isolated CPUs when isolcpus=managed_irq is in effect: those
        are expected on isolated CPUs and must not block allocation.

        The effective affinity (where the IRQ actually fires) is read when the
        kernel exposes it, the requested one otherwise. An IRQ counts only when
        that set is a subset of the isolated cores, the same rule as for
        threads: an IRQ left on its default all-CPUs affinity is not pinned
        and blocks nothing.
        """
        nic_irqs = set()
        for entry in glob.glob(
                os.path.join(self._sys, "class/net/*/device/msi_irqs/*")):
            try:
                nic_irqs.add(int(os.path.basename(entry)))
            except ValueError:
                continue

        busy = set()
        for irq_num in nic_irqs:
            irq_dir = os.path.join(self._proc, "irq", str(irq_num))
            cpus = set()
            for name in ("effective_affinity_list", "smp_affinity_list"):
                try:
                    with open(os.path.join(irq_dir, name)) as f:
                        cpus = set(parse_cpu_list(f.read()))
                except OSError:
                    continue
                if cpus:
                    break
            if cpus and cpus.issubset(isolated):
                busy.update(cpus)
        return busy

    def _claim_alive(self, claim: dict) -> bool:
        pid = claim.get("pid")
        if not pid:
            return True
        if not os.path.exists(os.path.join(self._proc, str(pid))):
            return False
        recorded = claim.get("start")
        if recorded is None:
            return True
        start = process_start_time(pid, self._proc)
        return start is None or start == recorded

    def _live_claims(self) -> list:
        """
        Claims whose owning process is still alive.

        Expired claims (PID gone from /proc, or reused by another process)
        are pruned and the file is rewritten. This is the self-healing
        mechanism: no daemon needed.
        """
        if self._claims_cache is not None:
            return self._claims_cache
        claims = self._load_claims()
        active = []
        for claim in claims:
            if not self._claim_alive(claim):
                log.debug("claim %r: pid %s gone, expiring",
                          claim.get("label"), claim.get("pid"))
                continue
            active.append(claim)
        if len(active) != len(claims):
            self._save_claims(active)
        self._claims_cache = active
        return active

    def _busy_by_claims(self, isolated: set) -> set:
        busy = set()
        for claim in self._live_claims():
            for c in claim.get("cores", []):
                if c in isolated:
                    busy.add(c)
        return busy

    def _live_slots(self) -> list:
        """
        Slots that still have at least one live member on their cores.

        Membership is derived from the actor sources only (pinned threads,
        claims, NIC IRQs), never from the slot source itself, which would be
        circular. A memberless slot within the creation grace period is kept
        so that a freshly created slot survives until its first member is
        pinned. Expired slots are pruned and the file rewritten, unless a PID
        is excluded: an exclusion makes the slot of a running VM look
        memberless on purpose.
        """
        if self._slots_cache is not None:
            return self._slots_cache
        slots = self._load_slots()
        if not slots:
            self._slots_cache = []
            return []
        occupied = self.occupied_cpus() | self.irq_cpus()
        now = _boot_seconds()
        active = []
        for slot in slots:
            cores = set(slot.get("cores", []))
            # A creation time ahead of now comes from an older wall-clock
            # entry: it gets no grace.
            in_grace = 0 <= now - slot.get("created", 0) <= _SLOT_GRACE_SECONDS
            if cores & occupied or in_grace:
                active.append(slot)
            else:
                log.debug("slot %r: no live member, expiring", slot.get("name"))
        if len(active) != len(slots) and not self._excluded_pids:
            self._save_slots(active)
        self._slots_cache = active
        return active

    def _busy_reserved_siblings(self, occupied: set) -> set:
        """
        Idle HT siblings reserved for exclusive_physical allocations.

        Each entry is [idle_cpu, active_cpu]. The reservation is valid only
        while active_cpu is still occupied by a live actor: a pinned thread
        (VM), an active claim (seapath-run, quadlet, ...) or an active slot
        (whose members may be IRQs, invisible to the other two). Stale
        entries (actor gone) are dropped automatically, but only from the
        file when no PID is excluded: an exclusion makes the entries of a
        running VM look stale on purpose.
        """
        entries = self._load_reserved_siblings()
        valid = []
        busy = set()
        for idle, active in entries:
            if active not in occupied:
                log.debug("reserved sibling %d (active=%d) lapsed", idle, active)
                continue
            valid.append([idle, active])
            busy.add(idle)
        if len(valid) != len(entries) and not self._excluded_pids:
            self._save_reserved_siblings(valid)
        return busy

    # ------------------------------------------------------------------ persistence

    def _write_json(self, path: str, data, **kwargs):
        """
        Replace path atomically: a hook killed mid-write must not leave an
        empty or truncated file, which would load as "no claims".
        """
        os.makedirs(self._alloc_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, 'w') as f:
            json.dump(data, f, **kwargs)
        os.replace(tmp, path)

    def _load_reserved_siblings(self) -> list:
        try:
            with open(self._reserved_file) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return []

    def _save_reserved_siblings(self, entries: list):
        self._write_json(self._reserved_file, entries)

    def _load_claims(self) -> list:
        try:
            with open(self._claims_file) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return []

    def _save_claims(self, claims: list):
        self._write_json(self._claims_file, claims, indent=2)

    def _load_slots(self) -> list:
        try:
            with open(self._slots_file) as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return []

    def _save_slots(self, slots: list):
        self._write_json(self._slots_file, slots, indent=2)
