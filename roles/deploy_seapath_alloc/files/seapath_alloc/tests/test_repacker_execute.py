# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for execute_repack() and the exhausted-receiver path of the planner."""

import subprocess

import pytest

from seapath_alloc import repacker as repacker_mod
from seapath_alloc.repacker import (
    CgroupMove,
    ThreadMove,
    execute_repack,
    find_repack_moves,
)


@pytest.fixture
def taskset(monkeypatch):
    """Record taskset invocations, optionally failing them."""
    def install(returncode=0, error=None):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if error:
                raise error
            return subprocess.CompletedProcess(cmd, returncode, stdout="",
                                               stderr="operation not permitted")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return calls

    return install


@pytest.fixture
def cgroup(monkeypatch):
    """Stand in for the cgroup helpers execute_repack imports lazily."""
    state = {"cpuset": [], "taskset": []}

    def install(root="/sys/fs/cgroup/system.slice/redis.service", pids=(4242,)):
        monkeypatch.setattr("seapath_alloc.cgroup.cgroup_root", lambda s: root)
        monkeypatch.setattr("seapath_alloc.cgroup.cgroup_procs",
                            lambda r: list(pids))
        monkeypatch.setattr(
            "seapath_alloc.cgroup.apply_cpuset",
            lambda r, cpus: state["cpuset"].append((r, cpus)),
        )
        monkeypatch.setattr(
            "seapath_alloc.cgroup.taskset_procs",
            lambda p, cpus: state["taskset"].append((p, cpus)),
        )
        return state

    return install


class FakePool:
    def __init__(self):
        self.moved = []

    def move_claim_cpu(self, label, cpu):
        self.moved.append((label, cpu))


# --- thread moves ---------------------------------------------------------


def test_a_thread_move_tasksets_every_tid(taskset, caplog):
    calls = taskset()

    with caplog.at_level("INFO", logger=repacker_mod.log.name):
        execute_repack([ThreadMove(tids=[100, 101], from_cpu=4, to_cpu=8)])

    assert calls == [
        ["taskset", "-cp", "8", "100"],
        ["taskset", "-cp", "8", "101"],
    ]
    assert "moved tid 100 cpu 4 → cpu 8" in caplog.text


def test_a_failing_taskset_is_logged_and_the_repack_continues(taskset, caplog):
    calls = taskset(returncode=1)

    with caplog.at_level("WARNING", logger=repacker_mod.log.name):
        execute_repack([ThreadMove(tids=[100, 101], from_cpu=4, to_cpu=8)])

    assert len(calls) == 2
    assert "taskset failed for tid 100 (4→8)" in caplog.text
    assert "operation not permitted" in caplog.text


@pytest.mark.parametrize(
    "error",
    [subprocess.TimeoutExpired("taskset", 5), OSError("no such binary")],
)
def test_a_taskset_that_cannot_run_is_logged(taskset, caplog, error):
    taskset(error=error)

    with caplog.at_level("WARNING", logger=repacker_mod.log.name):
        execute_repack([ThreadMove(tids=[100], from_cpu=4, to_cpu=8)])

    assert "taskset error for tid 100" in caplog.text


def test_an_empty_move_list_does_nothing(taskset):
    calls = taskset()

    execute_repack([])

    assert calls == []


# --- quadlet moves --------------------------------------------------------


def test_a_quadlet_move_updates_the_cpuset_then_the_running_processes(
    cgroup, caplog
):
    state = cgroup()

    with caplog.at_level("INFO", logger=repacker_mod.log.name):
        execute_repack([CgroupMove(label="redis", service="redis.service",
                                   from_cpu=4, to_cpu=8)])

    # The cpuset governs new processes; the taskset catches the running ones.
    assert state["cpuset"] == [
        ("/sys/fs/cgroup/system.slice/redis.service", "8")
    ]
    assert state["taskset"] == [([4242], "8")]
    assert "moved quadlet 'redis' cpu 4 → cpu 8" in caplog.text


def test_a_quadlet_move_updates_the_claim(cgroup):
    cgroup()
    pool = FakePool()

    execute_repack([CgroupMove(label="redis", service="redis.service",
                               from_cpu=4, to_cpu=8)], pool=pool)

    # Without this the claim keeps pointing at the old CPU and the new one
    # looks free to the next allocation.
    assert pool.moved == [("redis", 8)]


def test_a_quadlet_move_without_a_pool_still_migrates(cgroup):
    state = cgroup()

    execute_repack([CgroupMove(label="redis", service="redis.service",
                               from_cpu=4, to_cpu=8)])

    assert state["cpuset"]


def test_a_quadlet_whose_cgroup_is_gone_is_skipped(cgroup, caplog):
    state = cgroup(root=None)
    pool = FakePool()

    with caplog.at_level("WARNING", logger=repacker_mod.log.name):
        execute_repack([CgroupMove(label="redis", service="redis.service",
                                   from_cpu=4, to_cpu=8)], pool=pool)

    assert state["cpuset"] == []
    assert pool.moved == []
    assert "cgroup not found for redis.service" in caplog.text


def test_thread_and_quadlet_moves_are_applied_in_one_pass(taskset, cgroup):
    calls = taskset()
    state = cgroup()

    execute_repack([
        ThreadMove(tids=[100], from_cpu=4, to_cpu=8),
        CgroupMove(label="redis", service="redis.service", from_cpu=5,
                   to_cpu=9),
    ])

    assert calls == [["taskset", "-cp", "8", "100"]]
    assert state["cpuset"] == [
        ("/sys/fs/cgroup/system.slice/redis.service", "9")
    ]


# --- planner: no receiver -------------------------------------------------


class PlannerPool:
    """Minimal pool for find_repack_moves: a topology and four maps."""

    def __init__(self, topo, threads=None, quadlets=None, free=(), slots=()):
        self._topo = topo
        self._threads = threads or {}
        self._quadlets = quadlets or {}
        self._free = list(free)
        self._slots = set(slots)

    def free_logical(self):
        return self._free

    def slot_cores(self):
        return self._slots

    def pinned_workload_threads(self):
        return self._threads

    def pinned_quadlet_cpus(self):
        return self._quadlets


def test_the_planner_stops_when_no_receiver_pair_is_left(std_topology, caplog):
    # Pair (4,5) is a donor: only cpu4 is taken. Every other pair is full, so
    # the only free slot is the donor's own sibling, which cannot receive it.
    pool = PlannerPool(
        std_topology,
        threads={4: [100], 6: [102], 7: [103],
                 8: [104], 9: [105], 10: [106], 11: [107]},
        free=[5],
    )

    with caplog.at_level("DEBUG", logger=repacker_mod.log.name):
        moves = find_repack_moves(pool, needed_pairs=1)

    assert moves == []
