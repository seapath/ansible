# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for execute_repack() and the exhausted-receiver path of the planner."""

import subprocess

import pytest

from seapath_alloc import repacker as repacker_mod
from seapath_alloc.repacker import ThreadMove, execute_repack, find_repack_moves


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
