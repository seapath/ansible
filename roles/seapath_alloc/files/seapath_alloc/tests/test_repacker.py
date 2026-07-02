# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the REPACKING compaction helpers.

Topology: isolated 4-11, pairs (4,5)(6,7)(8,9)(10,11), housekeeping 0-3.

Scenario: guest1 holds cpu4 (exclusive_logical), guest2 holds cpu6 (exclusive_logical).
Both pairs (4,5) and (6,7) are "half-used" — one sibling busy, one free.
Repacking should be able to move one thread so that one pair becomes fully free.
"""

import json
import os
import pytest

from seapath_alloc.repacker import (
    CgroupMove, ThreadMove, execute_repack, find_repack_moves, find_spread_moves,
)
from .conftest import (
    make_cpu_topology, make_proc_qemu, make_proc_irq, make_sys_nic_irqs,
)


def _make_pool(tmp_path, reserved_pairs=None):
    """
    Build a CorePool with the standard 12-core topology.
    reserved_pairs: list of [idle, active] passed to pool.add_reserved_sibling.
    """
    sys_p = make_cpu_topology(tmp_path)
    from seapath_alloc.topology import Topology
    from seapath_alloc.pool import CorePool
    topo = Topology(sys_cpu_path=sys_p)
    pool = CorePool(
        topology=topo,
        proc_path=str(tmp_path / "proc"),
        sys_path=sys_p,
        alloc_dir=str(tmp_path / "run" / "seapath" / "alloc"),
    )
    pool.__enter__()
    if reserved_pairs:
        for idle, active in reserved_pairs:
            pool.add_reserved_sibling(idle, active)
    return pool


def _make_proc_run(tmp_path, pid: int, child_pid: int, cpu: int):
    """
    Build a fake /proc tree for a seapath-run process and its child workload.
    Both are pinned to `cpu`.
    """
    proc = tmp_path / "proc"

    def make_status(pid_dir, name, tgid, ppid, cpu_list):
        task = pid_dir / "task" / str(pid_dir.name)
        task.mkdir(parents=True, exist_ok=True)
        (task / "status").write_text(
            f"Name:\t{name}\n"
            f"Pid:\t{pid_dir.name}\n"
            f"Tgid:\t{tgid}\n"
            f"PPid:\t{ppid}\n"
            f"Cpus_allowed_list:\t{cpu_list}\n"
        )

    # seapath-run process
    sr_dir = proc / str(pid)
    sr_dir.mkdir(parents=True, exist_ok=True)
    make_status(sr_dir, "seapath-run", tgid=pid, ppid=1, cpu_list=str(cpu))

    # child workload (inherits affinity)
    ch_dir = proc / str(child_pid)
    ch_dir.mkdir(parents=True, exist_ok=True)
    make_status(ch_dir, "sv-simulator", tgid=child_pid, ppid=pid, cpu_list=str(cpu))


# ------------------------------------------------------------------ find_repack_moves

def test_find_repack_moves_one_pair_needed(tmp_path):
    """
    Two half-used pairs (one thread each on cpu4 and cpu6).
    Requesting 1 needed_pair should return exactly one move.
    """
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=1,
                   vcpu_cpus=[4])
    make_proc_qemu(tmp_path, pid=2000, vm_name="guest2", vcpu_count=1,
                   vcpu_cpus=[6])

    pool = _make_pool(tmp_path)
    moves = find_repack_moves(pool, needed_pairs=1)
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, ThreadMove)
    assert move.from_cpu in range(4, 12)
    assert move.to_cpu in range(4, 12)
    assert move.from_cpu != move.to_cpu


def test_find_repack_moves_two_pairs_frees_two_distinct(tmp_path):
    """
    Four half-used pairs (threads on 4,6,8,10), need 2 physical pairs.

    Regression: a pair that receives a moved thread must not also be chosen as
    a donor, otherwise the two moves free only one pair. The donor pairs and the
    receiver pairs must be disjoint so that two cores are genuinely freed.
    """
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=4,
                   vcpu_cpus=[4, 6, 8, 10])
    pool = _make_pool(tmp_path)
    moves = find_repack_moves(pool, needed_pairs=2)
    assert len(moves) == 2

    topo = pool._topo
    def lower(cpu):
        return min(topo.siblings_of(cpu))
    donor_pairs = {lower(m.from_cpu) for m in moves}
    receiver_pairs = {lower(m.to_cpu) for m in moves}
    assert len(donor_pairs) == 2
    assert donor_pairs.isdisjoint(receiver_pairs)


def test_find_repack_moves_moves_all_tids_of_core(tmp_path):
    """A donor core running a seapath-run parent + child moves BOTH tids."""
    alloc_dir = str(tmp_path / "run" / "seapath" / "alloc")
    os.makedirs(alloc_dir, exist_ok=True)
    fake_pid = os.getpid()
    with open(os.path.join(alloc_dir, "claims.json"), "w") as f:
        json.dump([{
            "label": "sv-sim", "pid": fake_pid, "cores": [4],
            "scheduler": "FIFO", "priority": 80, "kind": "run",
        }], f)
    _make_proc_run(tmp_path, pid=fake_pid, child_pid=fake_pid + 1, cpu=4)

    sys_p = make_cpu_topology(tmp_path)
    from seapath_alloc.topology import Topology
    from seapath_alloc.pool import CorePool
    topo = Topology(sys_cpu_path=sys_p)
    pool = CorePool(
        topology=topo,
        proc_path=str(tmp_path / "proc"),
        sys_path=sys_p,
        alloc_dir=alloc_dir,
    )
    pool.__enter__()

    moves = find_repack_moves(pool, needed_pairs=1)
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, ThreadMove)
    assert move.from_cpu == 4
    assert set(move.tids) == {fake_pid, fake_pid + 1}


def test_find_repack_moves_zero_needed(tmp_path):
    """Zero needed_pairs → no moves."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=1,
                   vcpu_cpus=[4])
    pool = _make_pool(tmp_path)
    moves = find_repack_moves(pool, needed_pairs=0)
    assert moves == []


def test_find_repack_moves_no_donors(tmp_path):
    """Both siblings of every pair are occupied → no donors."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=2,
                   vcpu_cpus=[4, 5])
    make_proc_qemu(tmp_path, pid=2000, vm_name="guest2", vcpu_count=2,
                   vcpu_cpus=[6, 7])
    pool = _make_pool(tmp_path)
    moves = find_repack_moves(pool, needed_pairs=1)
    assert moves == []


def test_find_repack_moves_no_threads(tmp_path):
    """No pinned actors at all → nothing to move."""
    pool = _make_pool(tmp_path)
    moves = find_repack_moves(pool, needed_pairs=1)
    assert moves == []


def test_find_repack_moves_all_donors(tmp_path):
    """
    Every isolated pair has exactly one sibling occupied (the lower sibling).
    No fully-free pair exists, so the repacker must use a donor pair's free
    sibling as the landing zone.

    Topology: pairs (4,5)(6,7)(8,9)(10,11), threads on 4,6,8,10.
    Expected: one move from a lower sibling to the free upper of another pair.
    """
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=4,
                   vcpu_cpus=[4, 6, 8, 10])
    pool = _make_pool(tmp_path)
    moves = find_repack_moves(pool, needed_pairs=1)
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, ThreadMove)
    assert move.from_cpu in (4, 6, 8, 10)
    assert move.to_cpu in (5, 7, 9, 11)
    from seapath_alloc.topology import Topology
    topo = Topology(sys_cpu_path=str(tmp_path / "sys"))
    assert set(topo.siblings_of(move.from_cpu)) != set(topo.siblings_of(move.to_cpu))


# ------------------------------------------------------------------ find_spread_moves

def test_find_spread_moves_two_dense_pairs(tmp_path):
    """
    Two dense pairs ((4,5) and (6,7) both fully occupied) and two empty pairs.
    Spread should move the upper sibling's thread of each dense pair.
    """
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=2,
                   vcpu_cpus=[4, 5])
    make_proc_qemu(tmp_path, pid=2000, vm_name="guest2", vcpu_count=2,
                   vcpu_cpus=[6, 7])
    pool = _make_pool(tmp_path)
    moves = find_spread_moves(pool)
    assert len(moves) == 2
    assert all(isinstance(m, ThreadMove) for m in moves)
    assert {m.from_cpu for m in moves} == {5, 7}
    assert {m.to_cpu for m in moves} == {8, 10}


def test_find_spread_moves_no_dense_pairs(tmp_path):
    """One thread per pair — already spread, nothing to do."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=3,
                   vcpu_cpus=[4, 6, 8])
    pool = _make_pool(tmp_path)
    moves = find_spread_moves(pool)
    assert moves == []


def test_find_spread_moves_one_dense_one_receiver(tmp_path):
    """One dense pair, multiple free pairs available — exactly one move."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=2,
                   vcpu_cpus=[4, 5])
    pool = _make_pool(tmp_path)
    moves = find_spread_moves(pool)
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, ThreadMove)
    assert move.from_cpu == 5
    assert move.to_cpu in (6, 8, 10)


def test_find_spread_moves_no_free_pairs(tmp_path):
    """All pairs occupied — no receiver pairs, no moves possible."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=8,
                   vcpu_cpus=[4, 5, 6, 7, 8, 9, 10, 11])
    pool = _make_pool(tmp_path)
    moves = find_spread_moves(pool)
    assert moves == []


def test_find_spread_moves_no_threads(tmp_path):
    """Empty system — nothing to move."""
    pool = _make_pool(tmp_path)
    moves = find_spread_moves(pool)
    assert moves == []


def test_find_spread_moves_seapath_run(tmp_path):
    """
    seapath-run process (and its child) on cpu4, QEMU thread on cpu5.
    Pair (4,5) is dense → spread should move the upper sibling (cpu5 thread)
    to a free pair.
    """
    alloc_dir = str(tmp_path / "run" / "seapath" / "alloc")
    os.makedirs(alloc_dir, exist_ok=True)
    fake_pid = os.getpid()
    # Register a run-kind claim for the seapath-run process
    with open(os.path.join(alloc_dir, "claims.json"), "w") as f:
        json.dump([{
            "label": "sv-sim", "pid": fake_pid, "cores": [4],
            "scheduler": "FIFO", "priority": 80, "kind": "run",
        }], f)

    _make_proc_run(tmp_path, pid=fake_pid, child_pid=fake_pid + 1, cpu=4)
    make_proc_qemu(tmp_path, pid=2000, vm_name="guest1", vcpu_count=1,
                   vcpu_cpus=[5])

    sys_p = make_cpu_topology(tmp_path)
    from seapath_alloc.topology import Topology
    from seapath_alloc.pool import CorePool
    topo = Topology(sys_cpu_path=sys_p)
    pool = CorePool(
        topology=topo,
        proc_path=str(tmp_path / "proc"),
        sys_path=sys_p,
        alloc_dir=alloc_dir,
    )
    pool.__enter__()

    moves = find_spread_moves(pool)
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, ThreadMove)
    # Upper sibling (cpu5, QEMU thread) should be moved out
    assert move.from_cpu == 5
    assert move.to_cpu in (6, 8, 10)


def test_find_spread_moves_irq_sibling(tmp_path):
    """
    A workload whose HT sibling carries a NIC IRQ shares a physical core with
    it. Spread must move the workload onto a fully-free pair, exactly as fresh
    SPREADING allocation avoids placing a logical thread next to an IRQ.
    """
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="g", vcpu_count=1,
                               vcpu_cpus=[5])
    cpu_sys = make_cpu_topology(tmp_path)
    make_proc_irq(tmp_path, {42: "4"}, proc_path=proc_path)   # IRQ on sibling of 5
    nic_sys = make_sys_nic_irqs(tmp_path, [42])

    from seapath_alloc.topology import Topology
    from seapath_alloc.pool import CorePool
    topo = Topology(sys_cpu_path=cpu_sys)
    alloc_dir = str(tmp_path / "run" / "seapath" / "alloc")
    os.makedirs(alloc_dir, exist_ok=True)
    pool = CorePool(topology=topo, proc_path=proc_path, sys_path=nic_sys,
                    alloc_dir=alloc_dir)
    pool.__enter__()

    moves = find_spread_moves(pool)
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, ThreadMove)
    assert move.from_cpu == 5            # the workload moves, not the IRQ
    assert move.to_cpu in (6, 8, 10)     # onto the T0 of a fully-free pair


def test_find_spread_moves_lone_workload_no_irq_stays(tmp_path):
    """A workload alone on its pair with a free sibling (no IRQ) is not moved."""
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="g", vcpu_count=1,
                               vcpu_cpus=[5])
    cpu_sys = make_cpu_topology(tmp_path)

    from seapath_alloc.topology import Topology
    from seapath_alloc.pool import CorePool
    topo = Topology(sys_cpu_path=cpu_sys)
    alloc_dir = str(tmp_path / "run" / "seapath" / "alloc")
    os.makedirs(alloc_dir, exist_ok=True)
    pool = CorePool(topology=topo, proc_path=proc_path,
                    sys_path="/nonexistent-sys", alloc_dir=alloc_dir)
    pool.__enter__()

    assert find_spread_moves(pool) == []


def test_find_spread_moves_quadlet(tmp_path):
    """
    Quadlet claim on cpu4, QEMU thread on cpu5 → dense pair → spread.
    The quadlet move must be a CgroupMove.
    """
    alloc_dir = str(tmp_path / "run" / "seapath" / "alloc")
    os.makedirs(alloc_dir, exist_ok=True)
    fake_pid = os.getpid()
    with open(os.path.join(alloc_dir, "claims.json"), "w") as f:
        json.dump([{
            "label": "my-app", "pid": fake_pid, "cores": [4],
            "scheduler": "FIFO", "priority": 50, "kind": "quadlet",
        }], f)

    # quadlet uses no_apply=True so no thread entry, but proc dir must exist
    # so _live_claims() doesn't expire the claim.
    (tmp_path / "proc" / str(fake_pid)).mkdir(parents=True, exist_ok=True)
    make_proc_qemu(tmp_path, pid=2000, vm_name="guest1", vcpu_count=1,
                   vcpu_cpus=[5])

    sys_p = make_cpu_topology(tmp_path)
    from seapath_alloc.topology import Topology
    from seapath_alloc.pool import CorePool
    topo = Topology(sys_cpu_path=sys_p)
    pool = CorePool(
        topology=topo,
        proc_path=str(tmp_path / "proc"),
        sys_path=sys_p,
        alloc_dir=alloc_dir,
    )
    pool.__enter__()

    moves = find_spread_moves(pool)
    # Dense pair (4,5): upper sibling is cpu5 (QEMU thread) → ThreadMove
    # OR lower sibling cpu4 (quadlet) → CgroupMove.
    # The algorithm picks the upper sibling (cpu5), so we expect a ThreadMove.
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, ThreadMove)
    assert move.from_cpu == 5


def test_find_spread_moves_quadlet_is_upper(tmp_path):
    """
    Quadlet claim on cpu5 (upper), QEMU thread on cpu4 (lower) → dense pair.
    Upper sibling is the quadlet → CgroupMove.
    """
    alloc_dir = str(tmp_path / "run" / "seapath" / "alloc")
    os.makedirs(alloc_dir, exist_ok=True)
    fake_pid = os.getpid()
    with open(os.path.join(alloc_dir, "claims.json"), "w") as f:
        json.dump([{
            "label": "my-app", "pid": fake_pid, "cores": [5],
            "scheduler": "FIFO", "priority": 50, "kind": "quadlet",
        }], f)

    (tmp_path / "proc" / str(fake_pid)).mkdir(parents=True, exist_ok=True)
    make_proc_qemu(tmp_path, pid=2000, vm_name="guest1", vcpu_count=1,
                   vcpu_cpus=[4])

    sys_p = make_cpu_topology(tmp_path)
    from seapath_alloc.topology import Topology
    from seapath_alloc.pool import CorePool
    topo = Topology(sys_cpu_path=sys_p)
    pool = CorePool(
        topology=topo,
        proc_path=str(tmp_path / "proc"),
        sys_path=sys_p,
        alloc_dir=alloc_dir,
    )
    pool.__enter__()

    moves = find_spread_moves(pool)
    assert len(moves) == 1
    move = moves[0]
    assert isinstance(move, CgroupMove)
    assert move.from_cpu == 5
    assert move.label == "my-app"
    assert move.service == "my-app.service"


# ------------------------------------------------------------------ execute_repack

def test_execute_repack_thread_move(tmp_path, monkeypatch):
    """execute_repack issues one taskset call per ThreadMove."""
    calls = []
    import subprocess

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    execute_repack([ThreadMove(tids=[1234], from_cpu=4, to_cpu=5)])
    assert len(calls) == 1
    assert calls[0] == ["taskset", "-cp", "5", "1234"]


def test_execute_repack_thread_move_all_tids(tmp_path, monkeypatch):
    """A ThreadMove with several tids issues one taskset call per tid."""
    calls = []
    import subprocess

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    execute_repack([ThreadMove(tids=[1234, 1235], from_cpu=4, to_cpu=5)])
    assert calls == [
        ["taskset", "-cp", "5", "1234"],
        ["taskset", "-cp", "5", "1235"],
    ]


def test_execute_repack_empty(tmp_path):
    """Empty move list completes without error."""
    execute_repack([])


# ------------------------------------------------------------------ slot exclusion

def test_repack_never_moves_slot_core(tmp_path):
    """A workload on a slot core is colocated with other actors: compaction
    must not select it as a donor even when it is the only candidate."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=1,
                   vcpu_cpus=[4])
    pool = _make_pool(tmp_path)
    pool.add_slot("s", [4], "exclusive_logical")

    moves = find_repack_moves(pool, needed_pairs=1)
    assert moves == []


def test_spread_never_moves_slot_core(tmp_path):
    """Two threads on the same pair, the upper one on a slot core: spreading
    must evacuate the non-slot thread instead of the slot member."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=2,
                   vcpu_cpus=[4, 5])
    pool = _make_pool(tmp_path)
    pool.add_slot("s", [5], "exclusive_logical")

    moves = find_spread_moves(pool)
    assert len(moves) == 1
    assert moves[0].from_cpu == 4


def test_spread_treats_slot_as_interferer(tmp_path):
    """A workload alone on its pair but with a slot on the HT sibling suffers
    the same interference as with a NIC IRQ: it must be moved to a free pair."""
    make_proc_qemu(tmp_path, pid=1000, vm_name="guest1", vcpu_count=1,
                   vcpu_cpus=[4])
    pool = _make_pool(tmp_path)
    pool.add_slot("s", [5], "exclusive_logical")

    moves = find_spread_moves(pool)
    assert len(moves) == 1
    assert moves[0].from_cpu == 4
    # Landing zone is a fully-free pair, away from the slot.
    assert moves[0].to_cpu in (6, 8, 10)
