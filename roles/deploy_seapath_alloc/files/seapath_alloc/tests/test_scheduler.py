# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the allocate_cores() pipeline — slot registration and joining.

Topology: isolated 4-11, pairs (4,5)(6,7)(8,9)(10,11), housekeeping 0-3.
"""

import os
import pytest

from seapath_alloc.allocator import AllocationStrategy
from seapath_alloc.pool import CorePool
from seapath_alloc.scheduler import allocate_cores
from seapath_alloc.topology import Topology
from .conftest import make_cpu_topology


@pytest.fixture
def locked_pool(tmp_path, monkeypatch):
    # Pin the strategy so the test does not depend on /etc/seapath/alloc.yaml
    # on the machine running the suite.
    monkeypatch.setattr("seapath_alloc.scheduler.load_strategy",
                        lambda: AllocationStrategy.SPREADING)
    sys_p = make_cpu_topology(tmp_path)
    topo = Topology(sys_cpu_path=sys_p)
    proc_path = str(tmp_path / "proc")
    os.makedirs(proc_path)
    pool = CorePool(
        topology=topo,
        proc_path=proc_path,
        sys_path="/nonexistent-sys-for-tests",
        alloc_dir=str(tmp_path / "alloc"),
    )
    pool.lock()
    yield pool, topo
    pool.unlock()


def _spec(name, slot, scheduler="FIFO", priority=10):
    return {"name": name, "slot": slot, "isolation": "exclusive_logical",
            "scheduler": scheduler, "priority": priority}


def test_allocate_cores_registers_new_slot(locked_pool):
    pool, topo = locked_pool
    result = allocate_cores(pool, [_spec("claim", "x")], topo, label="t")
    assert result.allocations[0].cpus == [4]
    slots = pool.slots()
    assert len(slots) == 1
    assert slots[0]["name"] == "x"
    assert slots[0]["cores"] == [4]
    assert slots[0]["isolation"] == "exclusive_logical"
    assert 4 not in pool.free_logical()


def test_allocate_cores_joins_slot_across_calls(locked_pool):
    """Second allocation referencing the same slot lands on the same core —
    the emulator/vhost and IRQ/process colocation use cases."""
    pool, topo = locked_pool
    r1 = allocate_cores(pool, [_spec("emulator", "x", "OTHER", 0)],
                        topo, label="vm1")
    r2 = allocate_cores(pool, [_spec("vhost/0", "x", "FIFO", 1)],
                        topo, label="vm1")
    assert r2.allocations[0].cpus == r1.allocations[0].cpus
    assert len(pool.slots()) == 1


def test_allocate_cores_distinct_slots_get_distinct_cores(locked_pool):
    pool, topo = locked_pool
    r1 = allocate_cores(pool, [_spec("a", "x")], topo, label="t")
    r2 = allocate_cores(pool, [_spec("b", "y")], topo, label="t")
    assert r1.allocations[0].cpus != r2.allocations[0].cpus
    assert {s["name"] for s in pool.slots()} == {"x", "y"}
