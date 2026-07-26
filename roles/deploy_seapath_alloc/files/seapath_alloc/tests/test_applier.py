# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import subprocess

from seapath_alloc.allocator import GroupAllocation
from seapath_alloc.applier import _apply_one


def _record_calls(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


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
