# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Live view of isolated CPU core occupancy on the local node.

State is derived entirely from the kernel at call time — no persistent
allocation database. The kernel is the source of truth:

  /proc/<pid>/task/<tid>/status   Cpus_allowed_list field
  /proc/irq/*/smp_affinity_list   NIC IRQ affinity

The only persistent files we write are .reserved_siblings, which tracks the
idle HT sibling of each exclusive_physical allocation, and slots.json, which
tracks named shared-core slots. Both self-heal: a reserved-sibling entry is
discarded the next time the pool is read if the active sibling is no longer
pinned by a live QEMU thread, and a slot is discarded once no live actor
(QEMU thread, claim, NIC IRQ) occupies any of its cores.

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


def _is_qemu_comm(comm: str) -> bool:
    """True if the thread name belongs to a QEMU workload thread."""
    return (
        comm.startswith('qemu')
        or bool(re.match(r'^CPU \d+/KVM$', comm))
        or comm.startswith('vhost')
        or comm.startswith('iothread')
    )


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

        self._lock_file = os.path.join(alloc_dir, ".lock")
        self._reserved_file = os.path.join(alloc_dir, ".reserved_siblings")
        self._claims_file = os.path.join(alloc_dir, "claims.json")
        self._slots_file = os.path.join(alloc_dir, "slots.json")

        # Memoized after first call to _busy_cpus(); invalidated by mutations.
        self._busy_cache = None
        # PIDs whose /proc threads are ignored in busy accounting.
        # Set via exclude_pids() before the first free_logical()/free_physical()
        # call to allow re-allocating a running VM onto its own current CPUs.
        self._excluded_pids: set = set()

    # ------------------------------------------------------------------ locking

    def lock(self):
        """Acquire exclusive flock. Call before any read or write."""
        os.makedirs(self._alloc_dir, exist_ok=True)
        self._lock_fd = open(self._lock_file, 'w')
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
        log.debug("flock acquired")

    def unlock(self):
        if self._lock_fd is not None:
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

    def add_reserved_sibling(self, idle_cpu: int, active_cpu: int):
        """
        Record that idle_cpu is the idle HT sibling of an exclusive_physical
        allocation whose thread is pinned to active_cpu.

        The reservation expires automatically when active_cpu disappears from
        QEMU affinities (VM died), so no explicit release is needed.
        """
        entries = self._load_reserved_siblings()
        entries.append([idle_cpu, active_cpu])
        self._save_reserved_siblings(entries)
        self.bust_cache()

    def add_claim(self, label: str, pid: int, cores: list,
                  scheduler: str = "OTHER", priority: int = 0,
                  kind: str = "", slot: str = ""):
        """Register a claim from a container or operator tool."""
        claims = self._load_claims()
        claims = [c for c in claims if c.get("label") != label]
        entry = {
            "label": label,
            "pid": pid,
            "cores": list(cores),
            "scheduler": scheduler,
            "priority": priority,
        }
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
            "created": int(time.time()),
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

        Only entries whose active_cpu is still occupied by a live actor (QEMU
        thread or active claim) are returned; stale entries are discarded.
        """
        isolated = set(self._topo.isolated_cpus())
        entries = self._load_reserved_siblings()
        currently_pinned = (self._busy_by_qemus(isolated)
                            | self._busy_by_claims(isolated)
                            | self._busy_by_slots(isolated))
        return [(idle, active) for idle, active in entries
                if active in currently_pinned]

    # ------------------------------------------------------------------ discovery

    def _busy_cpus(self) -> set:
        if self._busy_cache is not None:
            return self._busy_cache
        isolated = set(self._topo.isolated_cpus())
        busy = set()
        busy.update(self._busy_by_qemus(isolated))
        busy.update(self._busy_by_irqs(isolated))
        busy.update(self._busy_by_claims(isolated))
        busy.update(self._busy_reserved_siblings(isolated))
        busy.update(self._busy_by_slots(isolated))
        self._busy_cache = busy
        return busy

    def exclude_pids(self, pids: set):
        """
        Exclude threads of these QEMU process PIDs from busy-CPU accounting.

        When re-allocating a running VM (hook "started begin" fired on a VM
        that is already up), the VM's threads are still pinned to their old
        CPUs in /proc.  Excluding the QEMU PID lets the pool see those CPUs
        as available so the hook can assign a fresh, optimal allocation.

        The reserved-siblings file self-heals: entries whose active_cpu is no
        longer seen as busy (because the PID is excluded) are treated as
        lapsed, freeing the idle sibling as well.

        Must be called before the first free_logical() / free_physical() call
        while the pool lock is held.
        """
        self._excluded_pids = pids
        self.bust_cache()

    def bust_cache(self):
        self._busy_cache = None

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
        m = re.match(r'vhost-(\d+)$', comm)
        return bool(m) and int(m.group(1)) in self._excluded_pids

    def _busy_by_qemus(self, isolated: set) -> set:
        """
        Isolated cores held by QEMU threads.

        A thread holds isolated cores when its Cpus_allowed_list is a subset
        of the isolated set. A thread on default all-CPUs affinity (which
        includes housekeeping cores) is not counted — it isn't pinned.
        """
        busy = set()
        pattern = os.path.join(self._proc, "*/task/*/status")
        for status_path in glob.glob(pattern):
            try:
                with open(status_path) as f:
                    content = f.read()
            except OSError:
                continue
            name_m = re.search(r'^Name:\s+(.+)', content, re.M)
            if not name_m:
                continue
            comm = name_m.group(1).strip()
            if not _is_qemu_comm(comm):
                continue
            if self._thread_excluded(status_path.split(os.sep), comm):
                continue
            allowed_m = re.search(r'^Cpus_allowed_list:\s+(\S+)', content, re.M)
            if not allowed_m:
                continue
            allowed = set(parse_cpu_list(allowed_m.group(1)))
            if allowed and allowed.issubset(isolated):
                busy.update(allowed)
        return busy

    def pinned_workload_threads(self) -> dict:
        """
        Return {cpu: [tid, ...]} for workload threads exclusively pinned to a
        single isolated CPU.  Used by the repacker to enumerate moveable threads.

        Covers QEMU threads (VMs) and seapath-run processes (claim kind="run")
        including their direct children, which inherit the affinity at exec time.
        Quadlet containers are excluded here — they are moved via cgroup cpuset
        and enumerated by pinned_quadlet_cpus() instead.

        Only threads with a single-CPU affinity mask within the isolated set are
        included: multi-CPU affinities are ignored because the repacker cannot
        move threads that span pairs.
        """
        isolated = set(self._topo.isolated_cpus())

        run_pids = {
            c["pid"] for c in self._live_claims()
            if c.get("kind") == "run" and c.get("pid")
        }

        result: dict = {}
        pattern = os.path.join(self._proc, "*/task/*/status")
        for status_path in glob.glob(pattern):
            parts = status_path.split(os.sep)
            try:
                with open(status_path) as f:
                    content = f.read()
            except OSError:
                continue
            name_m = re.search(r'^Name:\s+(.+)', content, re.M)
            if not name_m:
                continue
            comm = name_m.group(1).strip()
            if self._thread_excluded(parts, comm):
                continue

            is_qemu = _is_qemu_comm(comm)
            is_run = False
            if not is_qemu and run_pids:
                tgid_m = re.search(r'^Tgid:\s+(\d+)', content, re.M)
                ppid_m = re.search(r'^PPid:\s+(\d+)', content, re.M)
                tgid = int(tgid_m.group(1)) if tgid_m else 0
                ppid = int(ppid_m.group(1)) if ppid_m else 0
                is_run = tgid in run_pids or ppid in run_pids

            if not is_qemu and not is_run:
                continue

            allowed_m = re.search(r'^Cpus_allowed_list:\s+(\S+)', content, re.M)
            if not allowed_m:
                continue
            cpus = set(parse_cpu_list(allowed_m.group(1)))
            if len(cpus) != 1:
                continue
            cpu = next(iter(cpus))
            if cpu not in isolated:
                continue
            try:
                tid = int(parts[-2])
            except (ValueError, IndexError):
                continue
            result.setdefault(cpu, []).append(tid)
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
        Isolated cores pinned to physical NIC MSI IRQs.

        Only IRQs that belong to a physical NIC are counted, enumerated from
        /sys/class/net/*/device/msi_irqs/. This deliberately excludes
        kernel-managed MSI IRQs (e.g. NVMe, xHCI) that the driver subsystem
        routes to isolated CPUs when isolcpus=managed_irq is in effect — those
        are expected on isolated CPUs and must not block allocation.
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
            path = os.path.join(self._proc, "irq", str(irq_num),
                                "smp_affinity_list")
            try:
                with open(path) as f:
                    content = f.read().strip()
            except OSError:
                continue
            busy.update(set(parse_cpu_list(content)) & isolated)
        return busy

    def _live_claims(self) -> list:
        """
        Claims whose owning process is still alive.

        Expired claims (pid gone from /proc) are pruned and the file is
        rewritten. This is the self-healing mechanism — no daemon needed.
        """
        claims = self._load_claims()
        active = []
        changed = False
        for claim in claims:
            pid = claim.get("pid")
            if pid and not os.path.exists(os.path.join(self._proc, str(pid))):
                log.debug("claim %r: pid %d gone, expiring", claim.get("label"), pid)
                changed = True
                continue
            active.append(claim)
        if changed:
            self._save_claims(active)
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

        Membership is derived from the actor sources only (QEMU threads,
        claims, NIC IRQs) — never from the slot source itself, which would be
        circular. A memberless slot within the creation grace period is kept
        so that a freshly created slot survives until its first member is
        pinned. Expired slots are pruned and the file rewritten.
        """
        slots = self._load_slots()
        if not slots:
            return []
        isolated = set(self._topo.isolated_cpus())
        occupied = (self._busy_by_qemus(isolated)
                    | self._busy_by_claims(isolated)
                    | self._busy_by_irqs(isolated))
        now = int(time.time())
        active = []
        changed = False
        for slot in slots:
            cores = set(slot.get("cores", []))
            in_grace = now - slot.get("created", 0) <= _SLOT_GRACE_SECONDS
            if cores & occupied or in_grace:
                active.append(slot)
            else:
                log.debug("slot %r: no live member, expiring", slot.get("name"))
                changed = True
        if changed:
            self._save_slots(active)
        return active

    def _busy_by_slots(self, isolated: set) -> set:
        busy = set()
        for slot in self._live_slots():
            for c in slot.get("cores", []):
                if c in isolated:
                    busy.add(c)
        return busy

    def _busy_reserved_siblings(self, isolated: set) -> set:
        """
        Idle HT siblings reserved for exclusive_physical allocations.

        Each entry is [idle_cpu, active_cpu]. The reservation is valid only
        while active_cpu is still occupied by a live actor — a QEMU thread
        (VM), an active claim (seapath-run, quadlet, …), or an active slot
        (whose members may be IRQs, invisible to the other two sources).
        Stale entries (actor gone) are dropped automatically.
        """
        entries = self._load_reserved_siblings()
        currently_pinned = (self._busy_by_qemus(isolated)
                            | self._busy_by_claims(isolated)
                            | self._busy_by_slots(isolated))
        valid = []
        changed = False
        busy = set()
        for idle, active in entries:
            if active not in currently_pinned:
                log.debug("reserved sibling %d (active=%d) lapsed", idle, active)
                changed = True
                continue
            valid.append([idle, active])
            busy.add(idle)
        if changed:
            self._save_reserved_siblings(valid)
        return busy

    # ------------------------------------------------------------------ persistence

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
        os.makedirs(self._alloc_dir, exist_ok=True)
        with open(self._reserved_file, 'w') as f:
            json.dump(entries, f)

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
        os.makedirs(self._alloc_dir, exist_ok=True)
        with open(self._claims_file, 'w') as f:
            json.dump(claims, f, indent=2)

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
        os.makedirs(self._alloc_dir, exist_ok=True)
        with open(self._slots_file, 'w') as f:
            json.dump(slots, f, indent=2)
