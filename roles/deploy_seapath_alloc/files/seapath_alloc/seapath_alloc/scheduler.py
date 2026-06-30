# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Central allocation pipeline shared by all allocation paths.

allocate_cores() is the single place where strategy loading, optional
compaction (REPACKING), AllocationEngine, and reserved-sibling
registration happen.  All callers — QEMU hook, seapath-run/containers,
future tools — go through this function; they only differ in how they
discover the threads to pin and how they register their allocation.
"""

import logging

from .allocator import AllocationEngine, AllocationStrategy
from .config import load_strategy
from .exporter import record_fallback
from .repacker import execute_repack, find_repack_moves

log = logging.getLogger(__name__)


def allocate_cores(pool, specs: list, topo, *,
                   exclude_pids: set = None, label: str = "", pid: int = 0):
    """
    Run the full allocation pipeline against an already-locked CorePool.

    Steps:
      1. Optionally exclude PIDs from busy accounting (for re-pinning a
         running process onto its currently-held CPUs — see pool.exclude_pids).
      2. Load the allocation strategy from /etc/seapath/alloc.yaml.
      3. If REPACKING and there is a shortfall of free physical pairs,
         compact existing threads to free enough pairs before allocating.
      4. Run AllocationEngine with the active strategy.
      5. Register reserved HT siblings for exclusive_physical allocations.
      6. Log and record any fallback-to-housekeeping warnings.

    The caller must hold the pool lock (i.e. call this inside a
    ``with CorePool(...) as pool:`` block).  The caller is responsible
    for applying the resulting allocations to threads (taskset / chrt /
    apply_all) and for registering any explicit claim (pool.add_claim).

    Returns the AllocationResult from AllocationEngine.allocate().
    """
    if exclude_pids:
        pool.exclude_pids(exclude_pids)

    strategy = load_strategy()

    if strategy == AllocationStrategy.REPACKING:
        needed = sum(s.get("count", 1) for s in specs
                     if s.get("isolation") == "exclusive_physical")
        shortfall = max(0, needed - len(pool.free_physical()))
        if shortfall > 0:
            log.info("%s: repacking — %d pair(s) short, attempting compaction",
                     label, shortfall)
            moves = find_repack_moves(pool, shortfall)
            if moves:
                execute_repack(moves, pool=pool)
                pool.bust_cache()
                log.info("%s: repacking — applied %d move(s), free_physical=%s",
                         label, len(moves), pool.free_physical())
            else:
                log.warning("%s: repacking — no moves found", label)

    engine = AllocationEngine(
        free_logical=pool.free_logical(),
        free_physical=pool.free_physical(),
        housekeeping=topo.housekeeping_cpus(),
        sibling_of_fn=topo.siblings_of,
        strategy=strategy,
    )
    result = engine.allocate(specs)

    for idle, active in result.reserved_siblings:
        pool.add_reserved_sibling(idle, active)

    for spec, alloc in zip(specs, result.allocations):
        if not alloc.warning:
            continue
        requested = spec.get("isolation", "")
        if "housekeeping" in alloc.warning:
            log.error("%s: %s — no RT isolation, running on housekeeping cores",
                      label, alloc.name)
            record_fallback(label, alloc.name, requested, pid=pid, severity="hard")
        else:
            log.warning("%s: %s — RT isolation preserved, HT-pair guarantee lost",
                        label, alloc.name)
            record_fallback(label, alloc.name, requested, pid=pid, severity="soft")

    return result
