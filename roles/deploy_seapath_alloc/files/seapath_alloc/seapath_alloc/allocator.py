# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Pure CPU allocation logic — no I/O.

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
    name: str        # "vcpu/0", "emulator", "vhost/0", "iothread/0", …
    cpus: list       # assigned cores (list for taskset compatibility)
    scheduler: str   # FIFO | RR | OTHER | BATCH
    priority: int    # 1-99 for FIFO/RR; 0 for OTHER/BATCH
    warning: str = ""


@dataclass
class AllocationResult:
    allocations: List[GroupAllocation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # [[idle_cpu, active_cpu], ...] — to be written via pool.add_reserved_sibling()
    reserved_siblings: List[list] = field(default_factory=list)


class AllocationEngine:
    """
    Maps a list of group specs onto concrete cores.

    Consumes free_logical and free_physical greedily in order. Once a core
    is assigned it is removed from the local working copies so the next spec
    sees an updated pool — this is safe because the caller holds the flock,
    meaning no other process can grab the same cores concurrently.
    """

    def __init__(
        self,
        free_logical: list,
        free_physical: list,
        housekeeping: list,
        sibling_of_fn,
        strategy: AllocationStrategy = AllocationStrategy.SPREADING,
    ):
        """
        free_logical:   isolated cores available for exclusive_logical
        free_physical:  lower siblings of fully-free physical pairs
        housekeeping:   non-isolated fallback cores (scheduler decides placement)
        sibling_of_fn:  topology.siblings_of(cpu) → list of logical CPUs in the pair
        strategy:       controls how logical cores are ordered (see AllocationStrategy)
                        REPACKING is handled externally by hook.py; the engine
                        treats it identically to SPREADING.
        """
        self._physical = list(free_physical)
        self._housekeeping = list(housekeeping)
        self._sibling_of = sibling_of_fn

        if strategy == AllocationStrategy.PACKING:
            self._logical = self._pair_order(list(free_logical))
        else:
            self._logical = list(free_logical)

        # Tracks cores assigned during this round (not yet in /proc).
        self._assigned: set = set()

    def allocate(self, group_specs: list) -> AllocationResult:
        """
        group_specs: list of dicts with keys name, isolation, scheduler, priority,
        and optional count (number of cores to allocate for a shared group).
        Returns AllocationResult.
        """
        result = AllocationResult()
        for spec in group_specs:
            name = spec["name"]
            isolation = spec.get("isolation", "none")
            count = spec.get("count", 1)
            cpus, warning, new_reserved = self._pick(name, isolation, count=count)
            result.allocations.append(GroupAllocation(
                name=name,
                cpus=cpus,
                scheduler=spec.get("scheduler", "OTHER"),
                priority=spec.get("priority", 0),
                warning=warning,
            ))
            result.reserved_siblings.extend(new_reserved)
            if warning:
                result.warnings.append(f"{name}: {warning}")
        return result

    def _pick(self, name: str, isolation: str, count: int = 1):
        """Returns (cpus, warning, new_reserved_siblings)."""

        if isolation == "none":
            # No pinning at all. isolcpus= already removes isolated cores from
            # the default affinity mask, so an untouched thread naturally runs
            # across the whole housekeeping set. Pinning it to a single
            # housekeeping core would only crowd one CPU for no benefit.
            return [], "", []

        if isolation == "exclusive_logical":
            cpus = []
            for _ in range(count):
                core = self._take_logical()
                if core is None:
                    break
                cpus.append(core)
            if not cpus:
                w = "pool exhausted, falling back to housekeeping"
                log.warning("%s: %s", name, w)
                # Spread across the whole housekeeping set rather than crowding
                # a single core; the requested RT scheduler is still applied.
                hk = list(self._housekeeping) or [0]
                return hk, w, []
            if len(cpus) < count:
                log.warning("%s: only %d/%d logical cores available", name, len(cpus), count)
            return cpus, "", []

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
            if not cpus:
                # Degrade to exclusive_logical before giving up to housekeeping:
                # RT isolation is preserved, only the HT-sibling noise guarantee is lost.
                logical_cpus = []
                for _ in range(count):
                    core = self._take_logical()
                    if core is None:
                        break
                    logical_cpus.append(core)
                if logical_cpus:
                    w = "no free physical pair, degraded to exclusive_logical (HT sibling not reserved)"
                    log.warning("%s: %s", name, w)
                    return logical_cpus, w, []
                w = "pool exhausted, falling back to housekeeping (no RT isolation)"
                log.warning("%s: %s", name, w)
                hk = list(self._housekeeping) or [0]
                return hk, w, []
            if len(cpus) < count:
                log.warning("%s: only %d/%d physical pairs available", name, len(cpus), count)
            return cpus, "", reserved

        log.warning("%s: unknown isolation %r, using none", name, isolation)
        # Treat a typo'd isolation as "none": leave the thread unpinned.
        return [], f"unknown isolation {isolation!r}", []

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
