# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Pure CPU allocation logic, no I/O.

Takes a snapshot of available cores (from CorePool) and a list of
per-thread-group specs, and returns concrete core assignments.

The caller (hook.py) is responsible for:
  - holding the flock before calling allocate()
  - writing reserved_siblings back to the pool after allocation
  - applying the result via applier.py
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

log = logging.getLogger(__name__)


class AllocationStrategy(Enum):
    SPREADING = "spreading"   # one thread per physical core (better HT isolation)
    PACKING   = "packing"     # fill both siblings of a core before moving to next
    REPACKING = "repacking"   # spreading, but compact running logical threads on
                              # demand to free physical pairs for new allocations


@dataclass
class GroupAllocation:
    name: str        # "vcpu/0", "emulator", "vhost/0", "iothread/0", ...
    cpus: list       # assigned cores (list for taskset compatibility)
    scheduler: str   # FIFO | RR | OTHER | BATCH
    priority: int    # 1-99 for FIFO/RR; 0 for OTHER/BATCH
    warning: str = ""
    # "" when the request was met, SOFT when RT isolation was kept but the
    # group got less than asked (HT sibling not reserved, fewer cores), HARD
    # when it got no RT isolation at all.
    severity: str = ""


SOFT = "soft"
HARD = "hard"


@dataclass
class AllocationResult:
    allocations: List[GroupAllocation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # [[idle_cpu, active_cpu], ...] to be written via pool.add_reserved_sibling()
    reserved_siblings: List[list] = field(default_factory=list)
    # [[name, cores, isolation], ...]: slots created during this round, to be
    # written via pool.add_slot()
    new_slots: List[list] = field(default_factory=list)


class AllocationEngine:
    """
    Maps a list of group specs onto concrete cores.

    Consumes free_logical and free_physical greedily in order. Once a core
    is assigned it is removed from the local working copies so the next spec
    sees an updated pool: this is safe because the caller holds the flock,
    meaning no other process can grab the same cores concurrently.
    """

    def __init__(
        self,
        free_logical: list,
        free_physical: list,
        housekeeping: list,
        sibling_of_fn,
        strategy: AllocationStrategy = AllocationStrategy.SPREADING,
        existing_slots: dict = None,
    ):
        """
        free_logical:   isolated cores available for exclusive_logical
        free_physical:  lower siblings of fully-free physical pairs
        housekeeping:   non-isolated fallback cores (scheduler decides placement)
        sibling_of_fn:  topology.siblings_of(cpu) -> list of logical CPUs in the pair
        strategy:       controls how logical cores are ordered (see AllocationStrategy)
                        REPACKING's compaction step is done by scheduler.py
                        before the engine runs; the engine treats it
                        identically to SPREADING.
        existing_slots: {name: {"cores": [...], "isolation": ...}}: named
                        shared-core slots already registered in the pool.
                        Specs referencing a known slot join its cores instead
                        of consuming new ones.
        """
        self._physical = list(free_physical)
        self._housekeeping = list(housekeeping)
        self._sibling_of = sibling_of_fn
        self._slots = dict(existing_slots or {})

        if strategy == AllocationStrategy.PACKING:
            self._logical = self._pair_order(list(free_logical))
        else:
            self._logical = self._spread_order(list(free_logical))

        # Tracks cores assigned during this round (not yet in /proc).
        self._assigned: set = set()
        # Round-wide slot definitions, computed at the top of allocate().
        self._round_slot_defs: dict = {}

    def allocate(self, group_specs: list) -> AllocationResult:
        """
        group_specs: list of dicts with keys name, isolation, scheduler, priority,
        and optional count (number of cores to allocate for a shared group).
        Returns AllocationResult.
        """
        self._round_slot_defs = self._merge_slot_defs(group_specs)
        result = AllocationResult()
        for spec in group_specs:
            name = spec["name"]
            isolation = spec.get("isolation", "none")
            count = spec.get("count", 1)
            slot_name = spec.get("slot", "")
            if slot_name:
                cpus, warning, new_reserved, severity = self._pick_slot(
                    name, slot_name, isolation, spec, result)
            else:
                cpus, warning, new_reserved, severity = self._pick(
                    name, isolation, count=count)
            scheduler = spec.get("scheduler", "OTHER")
            priority = spec.get("priority", 0)
            if severity == HARD and scheduler.upper() in ("FIFO", "RR"):
                # An RT thread (often idle=poll in the guest) left among
                # Ceph, corosync and the kworkers would only have RT
                # throttling to keep it from starving them, right when the
                # pool is short, typically after a failover.
                warning += f", {scheduler} {priority} dropped to OTHER"
                log.warning("%s: %s %d dropped to OTHER outside the isolated cores",
                            name, scheduler, priority)
                scheduler, priority = "OTHER", 0
            result.allocations.append(GroupAllocation(
                name=name,
                cpus=cpus,
                scheduler=scheduler,
                priority=priority,
                warning=warning,
                severity=severity,
            ))
            result.reserved_siblings.extend(new_reserved)
            if warning:
                result.warnings.append(f"{name}: {warning}")
        return result

    def _merge_slot_defs(self, group_specs: list) -> dict:
        """
        Co-define each new slot from every spec of this round referencing it.

        Within one allocation round (one VM profile), the spec order is an
        implementation detail — vcpus → emulator → vhost — that the user does
        not control, so "first reference fixes the attributes" would make the
        slot's size depend on which group happens to be expanded first. All
        specs of the round therefore contribute to the definition: size is
        the largest count requested, isolation the strongest. First-creator
        semantics only apply across rounds (between VMs, between actors).
        """
        defs: dict = {}
        for spec in group_specs:
            slot_name = spec.get("slot", "")
            if not slot_name or slot_name in self._slots:
                continue
            if spec.get("isolation", "none") == "none":
                continue
            d = defs.setdefault(
                slot_name, {"count": 1, "isolation": "exclusive_logical"})
            d["count"] = max(d["count"], spec.get("count", 1))
            if spec.get("isolation") == "exclusive_physical":
                d["isolation"] = "exclusive_physical"
        return defs

    def _pick_slot(self, name: str, slot_name: str, isolation: str,
                   spec: dict, result: AllocationResult):
        """
        Resolve a spec that references a named shared-core slot.

        Join if the slot exists (in the pool or created earlier this round):
        the slot's cores are returned as-is, nothing is consumed. Otherwise
        create it — with the round-wide merged definition, see
        _merge_slot_defs() — through the regular isolation paths and register
        it in result.new_slots. A creation that falls back to housekeeping
        does NOT persist the slot: there are no cores to share, so each member
        degrades individually and the slot may still be created later if cores
        free up.

        Returns (cpus, warning, new_reserved_siblings, severity).
        """
        if isolation == "none":
            w = f"slot {slot_name!r} requested with isolation 'none', slot ignored"
            log.warning("%s: %s", name, w)
            return [], w, [], SOFT

        existing = self._slots.get(slot_name)
        if existing is not None:
            cores = list(existing.get("cores", []))
            if not cores or set(cores) & set(self._housekeeping):
                # A declared slot holds whatever cores the operator gave it,
                # possibly none or housekeeping ones: joining it would leave an
                # RT spec unpinned or beside the housekeeping load.
                return self._housekeeping_fallback(
                    name, f"slot {slot_name!r} has no isolated core"
                          f" (cores={cores}), left on housekeeping")
            # Attributes were fixed when the slot was created; a joiner asking
            # for something else joins anyway — the request cannot be honoured
            # without moving every other member.
            if "isolation" in spec and spec["isolation"] != existing["isolation"]:
                log.warning(
                    "%s: slot %r is %s, requested %s ignored",
                    name, slot_name, existing["isolation"], spec["isolation"])
            if "count" in spec and spec["count"] != len(existing["cores"]):
                log.warning(
                    "%s: slot %r has %d core(s), requested count %d ignored",
                    name, slot_name, len(existing["cores"]), spec["count"])
            return list(existing["cores"]), "", [], ""

        defn = self._round_slot_defs.get(
            slot_name, {"count": spec.get("count", 1), "isolation": isolation})
        cpus, warning, new_reserved, severity = self._pick(
            name, defn["isolation"], count=defn["count"])
        if severity == HARD:
            return cpus, warning, new_reserved, severity
        effective = "exclusive_logical" if severity else defn["isolation"]
        self._slots[slot_name] = {"cores": list(cpus), "isolation": effective}
        result.new_slots.append([slot_name, list(cpus), effective])
        log.info("slot %r created: cores=%s isolation=%s (by %s)",
                 slot_name, cpus, effective, name)
        return cpus, warning, new_reserved, severity

    def _pick(self, name: str, isolation: str, count: int = 1):
        """Returns (cpus, warning, new_reserved_siblings, severity)."""

        if isolation == "none":
            # No pinning at all. isolcpus= keeps isolated cores out of the
            # affinity init passes down, and libvirt 10.4.0 and later starts
            # QEMU on the online CPUs minus the isolated ones, so an untouched
            # thread naturally runs across the whole housekeeping set. Pinning
            # it to a single housekeeping core would only crowd one CPU for no
            # benefit. Older libvirt starts QEMU on every online CPU: the
            # scheduler still keeps it off the isolated ones in practice
            # (no load balancing there), without any guarantee.
            return [], "", [], ""

        if isolation == "exclusive_logical":
            cpus = self._take_logical_n(count)
            if not cpus:
                return self._housekeeping_fallback(
                    name, "pool exhausted, falling back to housekeeping")
            if len(cpus) < count:
                w = f"only {len(cpus)}/{count} logical cores available"
                log.warning("%s: %s", name, w)
                return cpus, w, [], SOFT
            return cpus, "", [], ""

        if isolation == "exclusive_physical":
            cpus = []
            reserved = []
            for _ in range(count):
                lower = self._take_physical()
                if lower is None:
                    break
                cpus.append(lower)
                siblings = self._sibling_of(lower)
                upper = next((s for s in siblings if s != lower), None)
                if upper is not None:
                    reserved.append([upper, lower])
                    if upper in self._logical:
                        self._logical.remove(upper)
            if len(cpus) == count:
                return cpus, "", reserved, ""
            # Top the missing cores up with logical ones before giving up to
            # housekeeping: RT isolation is preserved, only the HT-sibling
            # noise guarantee is lost for them.
            topped = self._take_logical_n(count - len(cpus))
            if not cpus and not topped:
                return self._housekeeping_fallback(
                    name, "pool exhausted, falling back to housekeeping")
            parts = []
            if topped:
                parts.append(
                    "no free physical pair, degraded to exclusive_logical"
                    " (HT sibling not reserved)" if not cpus else
                    f"only {len(cpus)}/{count} physical pairs,"
                    f" {len(topped)} core(s) degraded to exclusive_logical")
            if len(cpus) + len(topped) < count:
                parts.append(f"only {len(cpus) + len(topped)}/{count} cores available")
            w = ", ".join(parts)
            log.warning("%s: %s", name, w)
            return cpus + topped, w, reserved, SOFT

        log.warning("%s: unknown isolation %r, using none", name, isolation)
        # Treat a typo'd isolation as "none": leave the thread unpinned. It
        # asked for RT isolation and gets none, a hard fallback.
        return ([], f"unknown isolation {isolation!r}, left on housekeeping",
                [], HARD)

    def _housekeeping_fallback(self, name: str, warning: str):
        log.warning("%s: %s", name, warning)
        # Spread across the whole housekeeping set rather than crowding a
        # single core.
        hk = list(self._housekeeping) or [0]
        return hk, warning, [], HARD

    def _take_logical_n(self, count: int) -> list:
        cpus = []
        for _ in range(count):
            core = self._take_logical()
            if core is None:
                break
            cpus.append(core)
        return cpus

    def _take_logical(self) -> Optional[int]:
        for i, cpu in enumerate(self._logical):
            if cpu not in self._assigned:
                self._assigned.add(cpu)
                self._logical.pop(i)
                return cpu
        return None

    def _take_physical(self) -> Optional[int]:
        for i, cpu in enumerate(self._physical):
            if cpu not in self._assigned:
                self._assigned.add(cpu)
                self._physical.pop(i)
                return cpu
        return None

    def _spread_order(self, logical: list) -> list:
        """
        Reorder logical so that each thread lands on its own physical core.

        SPREADING strategy: one CPU of every fully free pair first, then the
        CPUs whose sibling is taken, then the second CPU of the pairs used by
        the first round, each group in numeric order. Numeric order alone
        only spreads when the kernel numbers siblings N and N+ncores.
        """
        free = set(logical)
        first = []
        widowed = []
        seen = set()
        for cpu in logical:
            pair = frozenset(self._sibling_of(cpu)) | {cpu}
            if not pair <= free:
                widowed.append(cpu)
            elif pair not in seen:
                seen.add(pair)
                first.append(cpu)
        placed = set(first) | set(widowed)
        return first + widowed + [c for c in logical if c not in placed]

    def _pair_order(self, logical: list) -> list:
        """
        Reorder logical so each CPU is immediately followed by its sibling.

        PACKING strategy: fill both threads of a physical core before advancing
        to the next, reducing the number of active cores (better cache utilisation
        at the cost of HT interference between co-pinned threads).

        CPUs with no sibling in the list (or no sibling at all) are appended
        after all pairs, preserving their relative order.
        """
        remaining = list(logical)
        ordered = []
        while remaining:
            cpu = remaining.pop(0)
            ordered.append(cpu)
            siblings = self._sibling_of(cpu)
            for sib in siblings:
                if sib != cpu and sib in remaining:
                    remaining.remove(sib)
                    ordered.append(sib)
                    break
        return ordered
