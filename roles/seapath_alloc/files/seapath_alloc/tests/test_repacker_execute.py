# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for execute_repack() and the exhausted-receiver path of the planner."""

import subprocess

import pytest

from seapath_alloc import repacker as repacker_mod
from seapath_alloc.cgroup import Placement
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
    state = {"cpuset": []}

    def install(root="/sys/fs/cgroup/system.slice/redis.service",
                placement=Placement(cpuset=True, refused=0)):
        monkeypatch.setattr("seapath_alloc.cgroup.cgroup_root", lambda s: root)

        def fake_place(r, cpus, hk):
            state["cpuset"].append((r, cpus, hk))
            return placement

        monkeypatch.setattr("seapath_alloc.cgroup.place_service", fake_place)
        return state

    return install


class FakeTopology:
    def housekeeping_cpus(self):
        return [0, 1, 2, 3]


class FakePool:
    def __init__(self):
        self.moved = []
        self._topo = FakeTopology()

    def topology(self):
        return self._topo

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


class ClaimPool:
    def __init__(self, claims):
        self.claims = claims
        self.moved = []

    def all_claims(self):
        return self.claims

    def move_claim_cpu(self, label, cpu):
        self.moved.append((label, cpu))


def test_a_run_claim_follows_its_threads(taskset):
    taskset()
    pool = ClaimPool([
        {"label": "sv", "cores": [4], "kind": "run"},
        {"label": "other", "cores": [4, 6], "kind": "run"},
        {"label": "box", "cores": [4], "kind": "quadlet"},
    ])

    execute_repack([ThreadMove(tids=[100], from_cpu=4, to_cpu=8)], pool=pool)

    assert pool.moved == [("sv", 8)]


@pytest.mark.parametrize("failure", [{"returncode": 1},
                                     {"error": OSError("no such binary")}])
def test_a_run_claim_stays_when_a_thread_did_not_move(taskset, failure):
    taskset(**failure)
    pool = ClaimPool([{"label": "sv", "cores": [4], "kind": "run"}])

    execute_repack([ThreadMove(tids=[100], from_cpu=4, to_cpu=8)], pool=pool)

    assert pool.moved == []


def test_an_empty_move_list_does_nothing(taskset):
    calls = taskset()

    execute_repack([])

    assert calls == []


# --- quadlet moves --------------------------------------------------------


def test_a_quadlet_move_places_the_service_like_the_initial_pin(
    cgroup, caplog
):
    state = cgroup()

    with caplog.at_level("INFO", logger=repacker_mod.log.name):
        execute_repack([CgroupMove(label="redis", service="redis.service",
                                   from_cpu=4, to_cpu=8)], pool=FakePool())

    # Same split as seapath-container-pin: the payload on the new core,
    # conmon on the housekeeping cores, or the move would undo it.
    assert state["cpuset"] == [
        ("/sys/fs/cgroup/system.slice/redis.service", [8], [0, 1, 2, 3])
    ]
    assert "moved quadlet 'redis' cpu 4 → cpu 8" in caplog.text


def test_a_quadlet_move_on_a_real_tree(tmp_path, monkeypatch):
    # End to end through place_service: payload threads follow the core,
    # conmon stays on the housekeeping cores.
    root = tmp_path / "redis.service"
    payload = root / "libpod-payload-abc"
    runtime = root / "runtime"
    for d, tids in ((root, ()), (payload, (200, 201)), (runtime, (100,))):
        d.mkdir(parents=True, exist_ok=True)
        (d / "cpuset.cpus").write_text("4")
        (d / "cgroup.threads").write_text("".join(f"{t}\n" for t in tids))
    (root / "cpuset.cpus").write_text("0-4")
    affinity = []
    monkeypatch.setattr("seapath_alloc.cgroup.cgroup_root",
                        lambda s: str(root))
    monkeypatch.setattr("os.sched_setaffinity",
                        lambda tid, cpus: affinity.append((tid, sorted(cpus))),
                        raising=False)

    execute_repack([CgroupMove(label="redis", service="redis.service",
                               from_cpu=4, to_cpu=8)], pool=FakePool())

    assert (payload / "cpuset.cpus").read_text() == "8"
    assert (runtime / "cpuset.cpus").read_text() == "0-3"
    assert (root / "cpuset.cpus").read_text() == "0-3,8"
    assert affinity == [(200, [8]), (201, [8]), (100, [0, 1, 2, 3])]


def test_a_quadlet_move_updates_the_claim(cgroup):
    cgroup()
    pool = FakePool()

    execute_repack([CgroupMove(label="redis", service="redis.service",
                               from_cpu=4, to_cpu=8)], pool=pool)

    # Without this the claim keeps pointing at the old CPU and the new one
    # looks free to the next allocation.
    assert pool.moved == [("redis", 8)]


@pytest.mark.parametrize("placement, follows", [
    # The cpuset alone keeps the payload on its core, and so does the
    # affinity of every thread when the cpuset controller is not delegated.
    (Placement(cpuset=False, refused=0), True),
    (Placement(cpuset=True, refused=1), True),
    (Placement(cpuset=False, refused=1), False),
])
def test_a_quadlet_claim_follows_only_a_container_that_moved(
        cgroup, caplog, placement, follows):
    cgroup(placement=placement)
    pool = FakePool()

    with caplog.at_level("WARNING", logger=repacker_mod.log.name):
        execute_repack([CgroupMove(label="redis", service="redis.service",
                                   from_cpu=4, to_cpu=8)], pool=pool)

    assert pool.moved == ([("redis", 8)] if follows else [])
    assert ("quadlet 'redis' not moved" in caplog.text) is not follows


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
        ("/sys/fs/cgroup/system.slice/redis.service", [9], [])
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

    def topology(self):
        return self._topo

    def irq_cpus(self):
        return set()

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
