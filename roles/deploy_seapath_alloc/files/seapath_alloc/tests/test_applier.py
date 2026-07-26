# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import subprocess

import pytest

from seapath_alloc import applier
from seapath_alloc.allocator import GroupAllocation
from seapath_alloc.applier import _apply_one, _chrt, _taskset, apply_all
from seapath_alloc.threads import QemuThreads


def _record_calls(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _fail_calls(monkeypatch, failing="taskset", stderr="operation not permitted"):
    """Make one of the two tools exit non-zero, the other succeed."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        rc = 1 if cmd[0] == failing else 0
        return subprocess.CompletedProcess(cmd, returncode=rc, stdout="",
                                           stderr=stderr + "\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _alloc(name="vcpu/0", cpus=(4,), scheduler="FIFO", priority=90):
    return GroupAllocation(name=name, cpus=list(cpus), scheduler=scheduler,
                           priority=priority)


def test_apply_pinned_taskset_then_chrt(monkeypatch):
    calls = _record_calls(monkeypatch)
    _apply_one(42, GroupAllocation(name="vcpu/0", cpus=[4],
                                   scheduler="FIFO", priority=90))
    assert calls == [
        ["taskset", "-cp", "4", "42"],
        ["chrt", "-f", "-p", "90", "42"],
    ]


def test_apply_none_with_rt_scheduler_still_chrts(monkeypatch):
    """isolation=none + FIFO: no pinning, but the RT policy must be applied."""
    calls = _record_calls(monkeypatch)
    _apply_one(42, GroupAllocation(name="emulator", cpus=[],
                                   scheduler="FIFO", priority=10))
    assert calls == [["chrt", "-f", "-p", "10", "42"]]


def test_apply_none_with_other_scheduler_is_noop(monkeypatch):
    """isolation=none + OTHER: default affinity and policy, nothing to do."""
    calls = _record_calls(monkeypatch)
    _apply_one(42, GroupAllocation(name="vcpu/0", cpus=[],
                                   scheduler="OTHER", priority=0))
    assert calls == []


def test_taskset_raises_with_the_tool_error(monkeypatch):
    _fail_calls(monkeypatch, failing="taskset", stderr="No such process")

    with pytest.raises(RuntimeError) as excinfo:
        _taskset(42, [4, 5])

    assert "taskset -cp 4-5 42" in str(excinfo.value)
    assert "No such process" in str(excinfo.value)


def test_chrt_raises_with_the_tool_error(monkeypatch):
    _fail_calls(monkeypatch, failing="chrt", stderr="Invalid argument")

    with pytest.raises(RuntimeError) as excinfo:
        _chrt(42, "FIFO", 90)

    assert "chrt -f -p 90 42" in str(excinfo.value)
    assert "Invalid argument" in str(excinfo.value)


def test_chrt_falls_back_to_other_for_an_unknown_scheduler(monkeypatch):
    calls = _record_calls(monkeypatch)

    _chrt(42, "deadline", 0)

    assert calls == [["chrt", "-o", "-p", "0", "42"]]


def test_chrt_accepts_a_lowercase_scheduler(monkeypatch):
    calls = _record_calls(monkeypatch)

    _chrt(42, "fifo", 90)

    assert calls == [["chrt", "-f", "-p", "90", "42"]]


def test_a_failed_affinity_skips_the_scheduler(monkeypatch, caplog):
    """Pinning failed, so applying an RT policy would be actively dangerous."""
    calls = _fail_calls(monkeypatch, failing="taskset")

    with caplog.at_level("ERROR", logger=applier.log.name):
        _apply_one(42, _alloc())

    assert [c[0] for c in calls] == ["taskset"]
    assert "affinity failed for vcpu/0 tid=42" in caplog.text


def test_a_failed_scheduler_is_logged_and_swallowed(monkeypatch, caplog):
    calls = _fail_calls(monkeypatch, failing="chrt")

    with caplog.at_level("ERROR", logger=applier.log.name):
        _apply_one(42, _alloc())

    assert [c[0] for c in calls] == ["taskset", "chrt"]
    assert "scheduler failed for vcpu/0 tid=42" in caplog.text


def _threads(vcpus=2, vhosts=0, iothreads=0):
    return QemuThreads(
        pid=1000,
        emulator_tid=1000,
        vcpu_tids=[1010 + i for i in range(vcpus)],
        vhost_tids=[1020 + i for i in range(vhosts)],
        iothread_tids=[1030 + i for i in range(iothreads)],
    )


def test_apply_all_pins_vcpus_before_the_emulator(monkeypatch):
    """
    vhost kernel threads inherit the affinity of the thread that creates
    them, so the emulator has to be pinned before they appear.
    """
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=2, vhosts=1), [
        _alloc("vcpu/0", cpus=[4]),
        _alloc("vcpu/1", cpus=[5]),
        _alloc("emulator", cpus=[0]),
        _alloc("vhost", cpus=[1]),
    ])

    tids = [c[-1] for c in calls if c[0] == "taskset"]
    assert tids == ["1010", "1011", "1000", "1020"]


def test_apply_all_maps_each_vcpu_to_its_own_allocation(monkeypatch):
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=2), [
        _alloc("vcpu/0", cpus=[4]),
        _alloc("vcpu/1", cpus=[6]),
    ])

    assert [c[2] for c in calls if c[0] == "taskset"] == ["4", "6"]


def test_apply_all_skips_threads_with_no_allocation(monkeypatch):
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=3), [_alloc("vcpu/1", cpus=[5])])

    assert [c[-1] for c in calls if c[0] == "taskset"] == ["1011"]


def test_apply_all_shares_one_group_across_every_vhost(monkeypatch):
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=0, vhosts=3), [_alloc("vhost", cpus=[7])])

    pinned = [(c[2], c[-1]) for c in calls if c[0] == "taskset"]
    assert pinned == [("7", "1020"), ("7", "1021"), ("7", "1022")]


def test_apply_all_falls_back_to_per_index_vhost_allocations(monkeypatch):
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=0, vhosts=2), [
        _alloc("vhost/0", cpus=[7]),
        _alloc("vhost/1", cpus=[8]),
    ])

    assert [c[2] for c in calls if c[0] == "taskset"] == ["7", "8"]


def test_apply_all_shares_one_group_across_every_iothread(monkeypatch):
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=0, iothreads=2), [_alloc("iothread", cpus=[9])])

    assert [c[-1] for c in calls if c[0] == "taskset"] == ["1030", "1031"]


def test_apply_all_falls_back_to_per_index_iothread_allocations(monkeypatch):
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=0, iothreads=2), [
        _alloc("iothread/0", cpus=[9]),
        _alloc("iothread/1", cpus=[10]),
    ])

    assert [c[2] for c in calls if c[0] == "taskset"] == ["9", "10"]


def test_apply_all_with_no_allocations_does_nothing(monkeypatch):
    calls = _record_calls(monkeypatch)

    apply_all(_threads(vcpus=2, vhosts=1, iothreads=1), [])

    assert calls == []
