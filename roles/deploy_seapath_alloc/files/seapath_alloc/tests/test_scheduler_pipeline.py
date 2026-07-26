# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the parts of the allocate_cores() pipeline around the engine:
PID exclusion, repacking compaction, reserved siblings and fallback
reporting, plus declare_slot's warnings.

Topology: isolated 4-11, pairs (4,5)(6,7)(8,9)(10,11), housekeeping 0-3.
"""

import os

import pytest

from seapath_alloc import scheduler as scheduler_mod
from seapath_alloc.allocator import AllocationStrategy
from seapath_alloc.pool import CorePool
from seapath_alloc.scheduler import allocate_cores
from seapath_alloc.topology import Topology
from .conftest import make_cpu_topology


@pytest.fixture
def pool_at(tmp_path, monkeypatch):
    """A locked pool on the standard topology, with a chosen strategy."""
    def install(strategy=AllocationStrategy.SPREADING, isolated="4-11"):
        monkeypatch.setattr(scheduler_mod, "load_strategy", lambda: strategy)
        sys_p = make_cpu_topology(tmp_path, isolated=isolated)
        topo = Topology(sys_cpu_path=sys_p)
        proc_path = str(tmp_path / "proc")
        os.makedirs(proc_path, exist_ok=True)
        pool = CorePool(
            topology=topo,
            proc_path=proc_path,
            sys_path="/nonexistent-sys-for-tests",
            alloc_dir=str(tmp_path / "alloc"),
        )
        pool.lock()
        install.opened.append(pool)
        return pool, topo

    install.opened = []
    yield install
    for pool in install.opened:
        pool.unlock()


def spec(name="claim", isolation="exclusive_logical", **extra):
    base = {"name": name, "isolation": isolation, "scheduler": "OTHER",
            "priority": 0}
    base.update(extra)
    return base


# --- PID exclusion --------------------------------------------------------


def test_allocate_cores_excludes_the_callers_own_pids(pool_at):
    pool, topo = pool_at()
    excluded = []
    pool.exclude_pids = excluded.append

    allocate_cores(pool, [spec()], topo, exclude_pids={4242}, label="t")

    assert excluded == [{4242}]


def test_allocate_cores_without_exclusions_leaves_the_pool_alone(pool_at):
    pool, topo = pool_at()
    called = []
    pool.exclude_pids = called.append

    allocate_cores(pool, [spec()], topo, label="t")

    assert called == []


# --- reserved siblings ----------------------------------------------------


def test_allocate_cores_registers_the_idle_ht_sibling(pool_at):
    pool, topo = pool_at()
    registered = []
    pool.add_reserved_sibling = lambda idle, active: registered.append(
        (idle, active)
    )

    result = allocate_cores(
        pool, [spec(isolation="exclusive_physical")], topo, label="t"
    )

    assert result.allocations[0].cpus == [4]
    # 5 is the HT partner of 4: blocked, so nothing else lands on the pair.
    assert registered == [(5, 4)]


# --- repacking ------------------------------------------------------------


@pytest.fixture
def repack(monkeypatch):
    """Replace the repacker so the compaction decision can be observed."""
    state = {"asked": [], "applied": []}

    def install(moves=()):
        monkeypatch.setattr(
            scheduler_mod, "find_repack_moves",
            lambda pool, shortfall: (state["asked"].append(shortfall),
                                     list(moves))[1],
        )
        monkeypatch.setattr(
            scheduler_mod, "execute_repack",
            lambda m, pool=None: state["applied"].append(m),
        )
        return state

    return install


def test_repacking_compacts_when_pairs_are_short(pool_at, repack,
                                                 caplog):
    # One isolated pair, two exclusive_physical specs: one pair short.
    pool, topo = pool_at(strategy=AllocationStrategy.REPACKING, isolated="4-5")
    state = repack(moves=["a move"])

    with caplog.at_level("INFO", logger=scheduler_mod.log.name):
        allocate_cores(
            pool,
            [spec(name="a", isolation="exclusive_physical"),
             spec(name="b", isolation="exclusive_physical")],
            topo, label="VM vm0",
        )

    assert state["asked"] == [1]
    assert state["applied"] == [["a move"]]
    assert "1 pair(s) short, attempting compaction" in caplog.text
    assert "applied 1 move(s)" in caplog.text


def test_repacking_warns_when_nothing_can_be_moved(pool_at, repack,
                                                   caplog):
    pool, topo = pool_at(strategy=AllocationStrategy.REPACKING, isolated="4-5")
    state = repack(moves=[])

    with caplog.at_level("WARNING", logger=scheduler_mod.log.name):
        allocate_cores(
            pool,
            [spec(name="a", isolation="exclusive_physical"),
             spec(name="b", isolation="exclusive_physical")],
            topo, label="VM vm0",
        )

    assert state["applied"] == []
    assert "no moves found" in caplog.text


def test_repacking_does_nothing_when_there_are_enough_pairs(
    pool_at, repack
):
    pool, topo = pool_at(strategy=AllocationStrategy.REPACKING)
    state = repack(moves=["a move"])

    allocate_cores(pool, [spec(isolation="exclusive_physical")], topo,
                   label="t")

    assert state["asked"] == []


def test_repacking_ignores_specs_that_do_not_need_a_pair(
    pool_at, repack
):
    pool, topo = pool_at(strategy=AllocationStrategy.REPACKING, isolated="4-5")
    state = repack(moves=[])

    allocate_cores(pool, [spec(isolation="exclusive_logical"), spec(name="b")],
                   topo, label="t")

    assert state["asked"] == []


def test_repacking_honours_the_spec_count(pool_at, repack):
    pool, topo = pool_at(strategy=AllocationStrategy.REPACKING, isolated="4-5")
    state = repack(moves=[])

    allocate_cores(
        pool, [spec(isolation="exclusive_physical", count=3)], topo, label="t"
    )

    assert state["asked"] == [2]


# --- degradation reporting ------------------------------------------------


def test_allocate_cores_reports_a_hard_fallback(pool_at, caplog):
    # No isolated cores at all: everything lands on housekeeping.
    pool, topo = pool_at(isolated="")

    with caplog.at_level("ERROR", logger=scheduler_mod.log.name):
        allocate_cores(pool, [spec(name="vcpu/0")], topo, label="VM vm0")

    assert "no RT isolation, running on housekeeping cores" in caplog.text


def test_allocate_cores_reports_a_soft_fallback(pool_at, caplog):
    # cpu6 is isolated but cpu7 is not, so 6 is a free logical core that is
    # not part of any free pair: the second exclusive_physical spec keeps its
    # RT isolation but loses the HT-pair guarantee.
    pool, topo = pool_at(isolated="4-6")

    with caplog.at_level("WARNING", logger=scheduler_mod.log.name):
        allocate_cores(
            pool,
            [spec(name="a", isolation="exclusive_physical"),
             spec(name="b", isolation="exclusive_physical")],
            topo, label="VM vm0",
        )

    assert "HT-pair guarantee lost" in caplog.text


def test_allocate_cores_says_nothing_when_everything_fits(pool_at, caplog):
    pool, topo = pool_at()

    with caplog.at_level("WARNING", logger=scheduler_mod.log.name):
        allocate_cores(pool, [spec()], topo, label="t")

    assert caplog.text == ""
