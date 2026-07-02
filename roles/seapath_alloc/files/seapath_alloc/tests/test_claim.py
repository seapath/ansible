# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import subprocess
import types

import pytest
import yaml

from seapath_alloc import claim as claim_mod
from seapath_alloc.allocator import AllocationStrategy, GroupAllocation
from seapath_alloc.claim import claim, parse_isolation_arg, release


class FakePool:
    def __init__(self, slots=()):
        self._slots = list(slots)
        self.claims = []
        self.removed = []
        self.busted = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def slots(self):
        return self._slots

    def add_claim(self, label, pid, cpus, scheduler, priority, kind="", slot=""):
        self.claims.append({
            "label": label, "pid": pid, "cpus": cpus, "scheduler": scheduler,
            "priority": priority, "kind": kind, "slot": slot,
        })

    def remove_claim(self, label):
        self.removed.append(label)

    def bust_cache(self):
        self.busted = True


@pytest.fixture
def allocator(monkeypatch):
    """Replace the pool and the allocation engine, keep what they were asked."""
    state = {}

    def install(cpus=(4,), scheduler="OTHER", priority=0, slots=()):
        pool = FakePool(slots)
        state["pool"] = pool
        monkeypatch.setattr(claim_mod, "CorePool", lambda **kw: pool)
        monkeypatch.setattr(claim_mod, "Topology", lambda **kw: object())

        def fake_allocate(pool_arg, specs, topo, **kwargs):
            state["specs"] = specs
            state["kwargs"] = kwargs
            alloc = GroupAllocation(name="claim", cpus=list(cpus),
                                    scheduler=scheduler, priority=priority)
            return types.SimpleNamespace(allocations=[alloc])

        monkeypatch.setattr(claim_mod, "allocate_cores", fake_allocate)
        return state

    return install


@pytest.fixture
def run_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0),
    )
    return calls


# --- parse_isolation_arg --------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("exclusive_logical", ("exclusive_logical", "")),
        ("none", ("none", "")),
        ("slot:rt", ("exclusive_logical", "rt")),
        ("slot:rt:shared", ("shared", "rt")),
        ("slot:rt:", ("exclusive_logical", "rt")),
    ],
)
def test_parse_isolation_arg(value, expected):
    assert parse_isolation_arg(value) == expected


def test_parse_isolation_arg_rejects_an_empty_slot_name():
    with pytest.raises(ValueError, match="empty slot name"):
        parse_isolation_arg("slot:")


# --- profile files --------------------------------------------------------


def test_profile_file_is_read_as_a_mapping(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("isolation: shared\nscheduler: FIFO\n")

    assert claim_mod._load_profile_file(str(path)) == {
        "isolation": "shared", "scheduler": "FIFO",
    }


def test_a_profile_that_is_not_a_mapping_is_ignored(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("- one\n- two\n")

    assert claim_mod._load_profile_file(str(path)) == {}


def test_a_missing_profile_warns_and_is_ignored(tmp_path, caplog):
    with caplog.at_level("WARNING", logger=claim_mod.log.name):
        result = claim_mod._load_profile_file(str(tmp_path / "absent.yaml"))

    assert result == {}
    assert "could not load profile" in caplog.text


def test_an_unparsable_profile_warns_and_is_ignored(tmp_path, caplog):
    path = tmp_path / "p.yaml"
    path.write_text("isolation: [unclosed\n")

    with caplog.at_level("WARNING", logger=claim_mod.log.name):
        result = claim_mod._load_profile_file(str(path))

    assert result == {}
    assert "could not load profile" in caplog.text


def test_profiles_are_skipped_without_pyyaml(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(claim_mod, "yaml", None)

    with caplog.at_level("WARNING", logger=claim_mod.log.name):
        result = claim_mod._load_profile_file(str(tmp_path / "p.yaml"))

    assert result == {}
    assert "pyyaml not available" in caplog.text


# --- claim ----------------------------------------------------------------


def test_claim_registers_the_allocated_cores(allocator, run_calls):
    state = allocator(cpus=(4, 5))

    assert claim("sv", target_pid=4242) == [4, 5]
    assert state["pool"].claims == [{
        "label": "sv", "pid": 4242, "cpus": [4, 5], "scheduler": "OTHER",
        "priority": 0, "kind": "", "slot": "",
    }]


def test_claim_defaults_to_the_calling_process(allocator, run_calls, monkeypatch):
    state = allocator()
    monkeypatch.setattr(claim_mod.os, "getpid", lambda: 1234)

    claim("sv")

    assert state["pool"].claims[0]["pid"] == 1234
    assert state["kwargs"]["pid"] == 1234


def test_claim_records_the_actor_kind(allocator, run_calls):
    state = allocator()

    claim("redis", kind="container", target_pid=1)

    assert state["pool"].claims[0]["kind"] == "container"


def test_claim_builds_the_group_spec_from_its_arguments(allocator, run_calls):
    state = allocator()

    claim("sv", isolation="shared", scheduler="FIFO", priority=90, target_pid=1)

    assert state["specs"] == [{
        "name": "claim", "isolation": "shared", "scheduler": "FIFO",
        "priority": 90,
    }]


def test_claim_takes_its_settings_from_a_profile(allocator, run_calls, tmp_path):
    state = allocator()
    path = tmp_path / "p.yaml"
    path.write_text("isolation: shared\nscheduler: FIFO\npriority: 80\nslot: rt\n")

    claim("sv", profile_path=str(path), target_pid=1)

    assert state["specs"][0]["isolation"] == "shared"
    assert state["specs"][0]["scheduler"] == "FIFO"
    assert state["specs"][0]["priority"] == 80
    assert state["specs"][0]["slot"] == "rt"


def test_claim_keeps_its_arguments_when_the_profile_is_silent(
    allocator, run_calls, tmp_path
):
    state = allocator()
    path = tmp_path / "p.yaml"
    path.write_text("priority: 80\n")

    claim("sv", isolation="shared", target_pid=1)

    assert state["specs"][0]["isolation"] == "shared"


def test_claim_joins_an_existing_slot(allocator, run_calls):
    state = allocator(slots=[{"name": "rt"}])

    claim("sv", slot="rt", target_pid=1)

    assert state["specs"][0]["slot"] == "rt"
    assert state["pool"].claims[0]["slot"] == "rt"


def test_claim_does_not_record_a_slot_that_was_not_created(allocator, run_calls):
    # Slot creation that fell back to housekeeping leaves no slot behind, and
    # recording one would make the claim point at something that isn't there.
    state = allocator(slots=[])

    claim("sv", slot="rt", target_pid=1)

    assert state["pool"].claims[0]["slot"] == ""


def test_claim_pins_and_schedules_the_target(allocator, run_calls):
    allocator(cpus=(4, 5), scheduler="FIFO", priority=90)

    claim("sv", target_pid=4242)

    assert run_calls == [
        ["taskset", "-cp", "4-5", "4242"],
        ["chrt", "-f", "-p", "90", "4242"],
    ]


def test_claim_can_register_without_touching_the_process(allocator, run_calls):
    allocator(cpus=(4,))

    claim("sv", target_pid=4242, no_apply=True)

    assert run_calls == []


def test_claim_without_cores_still_applies_an_rt_policy(allocator, run_calls):
    """isolation=none + FIFO: default affinity, but the RT policy is honoured."""
    allocator(cpus=(), scheduler="FIFO", priority=10)

    claim("sv", target_pid=4242)

    assert run_calls == [["chrt", "-f", "-p", "10", "4242"]]


def test_claim_without_cores_and_without_rt_touches_nothing(allocator, run_calls):
    allocator(cpus=(), scheduler="OTHER")

    claim("sv", target_pid=4242)

    assert run_calls == []


def test_claim_falls_back_to_other_for_an_unknown_scheduler(allocator, run_calls):
    allocator(cpus=(4,), scheduler="DEADLINE", priority=0)

    claim("sv", target_pid=4242)

    assert run_calls[1] == ["chrt", "-o", "-p", "0", "4242"]


# --- release --------------------------------------------------------------


@pytest.fixture
def releaser(monkeypatch):
    """Wire release()'s deferred imports and report what they were asked."""
    state = {"applied": []}

    def install(strategy=AllocationStrategy.SPREADING, moves=()):
        pool = FakePool()
        state["pool"] = pool
        monkeypatch.setattr(claim_mod, "CorePool", lambda **kw: pool)
        monkeypatch.setattr(
            "seapath_alloc.config.load_strategy", lambda: strategy
        )
        monkeypatch.setattr(
            "seapath_alloc.repacker.find_spread_moves", lambda p: list(moves)
        )
        monkeypatch.setattr(
            "seapath_alloc.repacker.execute_repack",
            lambda m, pool=None: state["applied"].append((m, pool)),
        )
        return state

    return install


def test_release_removes_the_claim(releaser):
    state = releaser()

    release("sv")

    assert state["pool"].removed == ["sv"]
    assert state["applied"] == []


def test_release_does_not_spread_under_other_strategies(releaser):
    state = releaser(strategy=AllocationStrategy.PACKING, moves=["a move"])

    release("sv")

    assert state["applied"] == []


def test_release_spreads_the_freed_cores_under_repacking(releaser, caplog):
    state = releaser(strategy=AllocationStrategy.REPACKING, moves=["a move"])

    with caplog.at_level("INFO", logger=claim_mod.log.name):
        release("sv")

    moves, pool = state["applied"][0]
    assert moves == ["a move"]
    # pool= is what lets a quadlet spread update claims.json; without it the
    # claim keeps pointing at the old CPU and the new one looks free.
    assert pool is state["pool"]
    assert state["pool"].busted is True
    assert "spread after release of 'sv': 1 move(s)" in caplog.text


def test_release_under_repacking_with_nothing_to_move(releaser):
    state = releaser(strategy=AllocationStrategy.REPACKING, moves=[])

    release("sv")

    assert state["applied"] == []
    assert state["pool"].busted is False


def test_claim_degrades_gracefully_without_pyyaml():
    """python3-yaml is optional; profile files are then simply ignored."""
    import importlib
    import sys

    saved = sys.modules.get("yaml")
    sys.modules["yaml"] = None  # makes "import yaml" raise ImportError
    try:
        reloaded = importlib.reload(claim_mod)
        assert reloaded.yaml is None
    finally:
        if saved is None:
            del sys.modules["yaml"]
        else:
            sys.modules["yaml"] = saved
        importlib.reload(claim_mod)
