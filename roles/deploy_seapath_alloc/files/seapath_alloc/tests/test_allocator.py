# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Allocator tests.

Reference scenario (from the brief):
  Topology: isolated 4-11, pairs (4,5)(6,7)(8,9)(10,11), housekeeping 0-3
  guest2 already holds (4,5) and (6,7) via exclusive_physical.
  guest1 requests: 2 vCPUs exclusive_physical, emulator exclusive_logical,
                   2 vhost exclusive_logical.

Expected:
  vcpu/0  → core 8  (lower of (8,9))  reserved_sibling: [9, 8]
  vcpu/1  → core 10 (lower of (10,11)) reserved_sibling: [11, 10]
  emulator → pool exhausted (logical pool empty) → housekeeping fallback + WARNING
  vhost/0 → housekeeping fallback + WARNING
  vhost/1 → housekeeping fallback + WARNING
"""

import pytest
from seapath_alloc.allocator import AllocationEngine, AllocationStrategy


def make_engine(free_logical, free_physical, housekeeping, pairs,
                strategy=AllocationStrategy.SPREADING,
                existing_slots=None):
    sibling_map = {}
    for lo, hi in pairs:
        for c in range(lo, hi + 1):
            sibling_map[c] = [lo, hi]

    def sibling_of(cpu):
        return sibling_map.get(cpu, [cpu])

    return AllocationEngine(
        free_logical=free_logical,
        free_physical=free_physical,
        housekeeping=housekeeping,
        sibling_of_fn=sibling_of,
        strategy=strategy,
        existing_slots=existing_slots,
    )


ISOLATED_PAIRS = [(4, 5), (6, 7), (8, 9), (10, 11)]
HOUSEKEEPING = [0, 1, 2, 3]


# ------------------------------------------------------------------ none isolation

def test_none_leaves_thread_unpinned():
    # isolation=none assigns no cores: the thread is left on its default
    # (housekeeping) affinity rather than being pinned to a single core.
    engine = make_engine([4, 5, 6], [4, 6], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{"name": "x", "isolation": "none",
                                "scheduler": "OTHER", "priority": 0}])
    assert result.allocations[0].cpus == []
    assert result.allocations[0].warning == ""


# ------------------------------------------------------------------ exclusive_logical

def test_exclusive_logical_takes_first_free():
    engine = make_engine([4, 5, 6, 7, 8, 9, 10, 11], [4, 6, 8, 10],
                          HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([
        {"name": "a", "isolation": "exclusive_logical",
         "scheduler": "OTHER", "priority": 0},
        {"name": "b", "isolation": "exclusive_logical",
         "scheduler": "OTHER", "priority": 0},
    ])
    assert result.allocations[0].cpus == [4]
    assert result.allocations[1].cpus == [5]
    assert result.warnings == []


def test_exclusive_logical_fallback_when_pool_empty():
    engine = make_engine([], [4, 6], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{"name": "a", "isolation": "exclusive_logical",
                                "scheduler": "FIFO", "priority": 50}])
    # Fallback spreads across the whole housekeeping set, not a single core.
    assert result.allocations[0].cpus == HOUSEKEEPING
    assert result.allocations[0].warning != ""
    assert len(result.warnings) == 1


# ------------------------------------------------------------------ exclusive_physical

def test_exclusive_physical_pins_lower_reserves_upper():
    engine = make_engine([4, 5, 6, 7, 8, 9, 10, 11], [4, 6, 8, 10],
                          HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{"name": "v", "isolation": "exclusive_physical",
                                "scheduler": "FIFO", "priority": 90}])
    alloc = result.allocations[0]
    assert alloc.cpus == [4]       # pinned to lower sibling
    assert alloc.warning == ""
    assert [5, 4] in result.reserved_siblings  # upper, active


def test_exclusive_physical_degrades_to_logical_before_housekeeping():
    # Physical pool empty but logical still available → degrade, not housekeeping.
    engine = make_engine([8, 9], [], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{"name": "v", "isolation": "exclusive_physical",
                                "scheduler": "FIFO", "priority": 90}])
    alloc = result.allocations[0]
    assert alloc.cpus == [8]                      # got a logical core
    assert "exclusive_logical" in alloc.warning   # degraded, not housekeeping
    assert "housekeeping" not in alloc.warning


def test_exclusive_physical_degrades_to_logical_count():
    # count=2, no physical pairs, but 3 logical free → get 2 logical cores.
    engine = make_engine([8, 9, 10], [], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{"name": "v", "isolation": "exclusive_physical",
                                "scheduler": "FIFO", "priority": 90, "count": 2}])
    alloc = result.allocations[0]
    assert alloc.cpus == [8, 9]
    assert "exclusive_logical" in alloc.warning


def test_exclusive_physical_fallback_when_no_pairs():
    # Both pools empty → housekeeping fallback.
    engine = make_engine([], [], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{"name": "v", "isolation": "exclusive_physical",
                                "scheduler": "FIFO", "priority": 90}])
    assert result.allocations[0].cpus == HOUSEKEEPING
    assert "housekeeping" in result.allocations[0].warning


def test_exclusive_physical_consecutive_pairs():
    engine = make_engine([4, 5, 6, 7, 8, 9, 10, 11], [4, 6, 8, 10],
                          HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([
        {"name": "v0", "isolation": "exclusive_physical",
         "scheduler": "FIFO", "priority": 90},
        {"name": "v1", "isolation": "exclusive_physical",
         "scheduler": "FIFO", "priority": 90},
    ])
    assert result.allocations[0].cpus == [4]
    assert result.allocations[1].cpus == [6]
    reserved_idles = [r[0] for r in result.reserved_siblings]
    assert 5 in reserved_idles
    assert 7 in reserved_idles


# ------------------------------------------------------------------ reference scenario

def test_reference_scenario():
    """
    guest2 holds (4,5)(6,7) → free_logical=[8,9,10,11], free_physical=[8,10].
    guest1: 2×exclusive_physical vCPU + exclusive_logical emulator + 2×exclusive_logical vhost.
    """
    free_logical = [8, 9, 10, 11]
    free_physical = [8, 10]
    engine = make_engine(free_logical, free_physical, HOUSEKEEPING, ISOLATED_PAIRS)

    specs = [
        {"name": "vcpu/0",   "isolation": "exclusive_physical",  "scheduler": "FIFO", "priority": 90},
        {"name": "vcpu/1",   "isolation": "exclusive_physical",  "scheduler": "FIFO", "priority": 90},
        {"name": "emulator", "isolation": "exclusive_logical",   "scheduler": "FIFO", "priority": 50},
        {"name": "vhost/0",  "isolation": "exclusive_logical",   "scheduler": "FIFO", "priority": 50},
        {"name": "vhost/1",  "isolation": "exclusive_logical",   "scheduler": "FIFO", "priority": 50},
    ]
    result = engine.allocate(specs)

    by_name = {a.name: a for a in result.allocations}

    # vCPUs get the two available physical pairs
    assert by_name["vcpu/0"].cpus == [8]
    assert by_name["vcpu/1"].cpus == [10]
    assert by_name["vcpu/0"].warning == ""
    assert by_name["vcpu/1"].warning == ""

    # reserved siblings: 9→8, 11→10
    reserved_idles = {r[0]: r[1] for r in result.reserved_siblings}
    assert reserved_idles[9] == 8
    assert reserved_idles[11] == 10

    # emulator and vhost: logical pool now empty (8 and 10 consumed by physical,
    # 9 and 11 removed as upper siblings) → fallback to housekeeping
    assert by_name["emulator"].cpus == HOUSEKEEPING
    assert by_name["emulator"].warning != ""
    assert by_name["vhost/0"].warning != ""
    assert by_name["vhost/1"].warning != ""

    assert len(result.warnings) == 3


# ------------------------------------------------------------------ PACKING strategy

def test_packing_takes_sibling_before_next_pair():
    """
    PACKING: with 4 threads requesting exclusive_logical and pairs (4,5)(6,7),
    the first two threads should land on 4 and 5 (same physical core) before
    moving to core 6.
    """
    engine = make_engine(
        free_logical=[4, 5, 6, 7],
        free_physical=[4, 6],
        housekeeping=HOUSEKEEPING,
        pairs=ISOLATED_PAIRS,
        strategy=AllocationStrategy.PACKING,
    )
    specs = [
        {"name": f"vcpu/{i}", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 80}
        for i in range(4)
    ]
    result = engine.allocate(specs)
    cpus = [a.cpus[0] for a in result.allocations]
    # Siblings fill before advancing: 4,5 then 6,7
    assert cpus == [4, 5, 6, 7]


def test_spreading_interleaves_pairs():
    """
    SPREADING (default): threads spread across physical cores first.
    With free_logical=[4,5,6,7] in sorted order, assignment is 4,5,6,7
    (sorted order, not pair-interleaved) but the key difference from packing
    is that _pair_order is NOT called — we test the engine produces sorted order.
    """
    engine = make_engine(
        free_logical=[4, 5, 6, 7],
        free_physical=[4, 6],
        housekeeping=HOUSEKEEPING,
        pairs=ISOLATED_PAIRS,
        strategy=AllocationStrategy.SPREADING,
    )
    specs = [
        {"name": f"vcpu/{i}", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 80}
        for i in range(4)
    ]
    result = engine.allocate(specs)
    cpus = [a.cpus[0] for a in result.allocations]
    assert cpus == [4, 5, 6, 7]


def test_packing_partial_pairs():
    """
    PACKING with an odd number of threads: last thread goes to the lower
    sibling of the next pair (no sibling available to fill after it).
    """
    engine = make_engine(
        free_logical=[4, 5, 6],
        free_physical=[4, 6],
        housekeeping=HOUSEKEEPING,
        pairs=ISOLATED_PAIRS,
        strategy=AllocationStrategy.PACKING,
    )
    specs = [
        {"name": f"vcpu/{i}", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 80}
        for i in range(3)
    ]
    result = engine.allocate(specs)
    cpus = [a.cpus[0] for a in result.allocations]
    assert cpus == [4, 5, 6]


# ------------------------------------------------------------------ count > 1

def test_exclusive_physical_count_allocates_multiple_pairs():
    engine = make_engine([4, 5, 6, 7, 8, 9, 10, 11], [4, 6, 8, 10],
                          HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{
        "name": "vhost", "isolation": "exclusive_physical",
        "scheduler": "FIFO", "priority": 1, "count": 2,
    }])
    alloc = result.allocations[0]
    assert alloc.cpus == [4, 6]
    assert alloc.warning == ""
    reserved_idles = [r[0] for r in result.reserved_siblings]
    assert 5 in reserved_idles
    assert 7 in reserved_idles


def test_exclusive_logical_count_allocates_multiple_cores():
    engine = make_engine([4, 5, 6, 7], [4, 6], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{
        "name": "vhost", "isolation": "exclusive_logical",
        "scheduler": "FIFO", "priority": 1, "count": 3,
    }])
    alloc = result.allocations[0]
    assert alloc.cpus == [4, 5, 6]
    assert alloc.warning == ""


def test_count_partial_allocation_takes_available():
    """count=3 with only 1 pair available: allocate what we can.

    The shortfall is logged but not recorded as a fallback — the group did
    get isolated cores, just fewer than requested."""
    engine = make_engine([4, 5], [4], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{
        "name": "vhost", "isolation": "exclusive_physical",
        "scheduler": "FIFO", "priority": 1, "count": 3,
    }])
    alloc = result.allocations[0]
    assert alloc.cpus == [4]
    assert alloc.warning == ""


def test_count_zero_pairs_falls_back_to_housekeeping():
    engine = make_engine([], [], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([{
        "name": "vhost", "isolation": "exclusive_physical",
        "scheduler": "FIFO", "priority": 1, "count": 2,
    }])
    alloc = result.allocations[0]
    assert alloc.cpus == HOUSEKEEPING
    assert alloc.warning != ""


# ------------------------------------------------------------------ REPACKING strategy

def test_repacking_treated_as_spreading():
    """
    The REPACKING enum value reaches AllocationEngine as SPREADING-order
    (the compaction step is done by scheduler.py before the engine runs).
    """
    engine = make_engine(
        free_logical=[4, 5, 6, 7],
        free_physical=[4, 6],
        housekeeping=HOUSEKEEPING,
        pairs=ISOLATED_PAIRS,
        strategy=AllocationStrategy.REPACKING,
    )
    specs = [
        {"name": f"vcpu/{i}", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 80}
        for i in range(4)
    ]
    result = engine.allocate(specs)
    cpus = [a.cpus[0] for a in result.allocations]
    assert cpus == [4, 5, 6, 7]


# ------------------------------------------------------------------ slots

def test_slot_created_then_joined_same_round():
    """emulator creates the slot, vhost joins it: one core for both."""
    engine = make_engine([4, 5, 6, 7, 8, 9, 10, 11], [4, 6, 8, 10],
                          HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([
        {"name": "emulator", "slot": "x", "isolation": "exclusive_logical",
         "scheduler": "OTHER", "priority": 0},
        {"name": "vhost/0", "slot": "x", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 1},
    ])
    assert result.allocations[0].cpus == [4]
    assert result.allocations[1].cpus == [4]
    assert result.new_slots == [["x", [4], "exclusive_logical"]]
    assert result.warnings == []


def test_slot_join_existing_consumes_nothing():
    """Joining a pool-registered slot leaves the free lists untouched."""
    engine = make_engine([6], [6], HOUSEKEEPING, ISOLATED_PAIRS,
                          existing_slots={
                              "x": {"cores": [4],
                                    "isolation": "exclusive_logical"}})
    result = engine.allocate([
        {"name": "a", "slot": "x", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 10},
        {"name": "b", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 20},
    ])
    assert result.allocations[0].cpus == [4]
    assert result.allocations[1].cpus == [6]
    assert result.new_slots == []
    assert result.warnings == []


def test_slot_physical_creation_reserves_sibling():
    engine = make_engine([4, 5, 6, 7], [4, 6], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([
        {"name": "a", "slot": "x", "isolation": "exclusive_physical",
         "scheduler": "FIFO", "priority": 10},
    ])
    assert result.allocations[0].cpus == [4]
    assert result.reserved_siblings == [[5, 4]]
    assert result.new_slots == [["x", [4], "exclusive_physical"]]


def test_slot_creation_degraded_records_effective_isolation():
    """No free pair: the slot is created on a logical core and recorded as
    exclusive_logical (the effective level), with a soft warning."""
    engine = make_engine([5, 7], [], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([
        {"name": "a", "slot": "x", "isolation": "exclusive_physical",
         "scheduler": "FIFO", "priority": 10},
    ])
    assert result.allocations[0].cpus == [5]
    assert "degraded" in result.allocations[0].warning
    assert result.new_slots == [["x", [5], "exclusive_logical"]]


def test_slot_housekeeping_fallback_not_persisted():
    """Pool exhausted: the member degrades individually, no slot is created."""
    engine = make_engine([], [], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([
        {"name": "a", "slot": "x", "isolation": "exclusive_logical",
         "scheduler": "FIFO", "priority": 10},
    ])
    assert result.allocations[0].cpus == HOUSEKEEPING
    assert "housekeeping" in result.allocations[0].warning
    assert result.new_slots == []


def test_slot_with_isolation_none_is_ignored():
    engine = make_engine([4, 5], [4], HOUSEKEEPING, ISOLATED_PAIRS)
    result = engine.allocate([
        {"name": "a", "slot": "x", "isolation": "none",
         "scheduler": "OTHER", "priority": 0},
    ])
    assert result.allocations[0].cpus == []
    assert "slot" in result.allocations[0].warning
    assert result.new_slots == []


def test_slot_join_with_conflicting_attributes_joins_anyway():
    """Attributes are fixed by the creator: a conflicting joiner still joins
    and no new sibling reservation is made."""
    engine = make_engine([6, 7], [6], HOUSEKEEPING, ISOLATED_PAIRS,
                          existing_slots={
                              "x": {"cores": [4],
                                    "isolation": "exclusive_logical"}})
    result = engine.allocate([
        {"name": "a", "slot": "x", "isolation": "exclusive_physical",
         "scheduler": "FIFO", "priority": 10, "count": 2},
    ])
    assert result.allocations[0].cpus == [4]
    assert result.reserved_siblings == []
    assert result.new_slots == []
