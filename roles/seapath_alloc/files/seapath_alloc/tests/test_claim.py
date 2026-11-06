# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import subprocess
import types

import pytest
import yaml

from seapath_alloc import claim as claim_mod
from seapath_alloc.allocator import AllocationStrategy, GroupAllocation
from seapath_alloc.claim import claim, release


class FakePool:
    def __init__(self, live=()):
        self.live = list(live)
        self.claims = []
        self.removed = []
        self.busted = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def all_claims(self):
        return self.live

    def add_claim(self, label, pid, cpus, scheduler, priority, kind=""):
        self.claims.append({
            "label": label, "pid": pid, "cpus": cpus, "scheduler": scheduler,
            "priority": priority, "kind": kind,
        })

    def remove_claim(self, label):
        self.removed.append(label)

    def bust_cache(self):
        self.busted = True


@pytest.fixture
def allocator(monkeypatch):
    """Replace the pool and the allocation engine, keep what they were asked."""
    state = {}

    def install(cpus=(4,), scheduler="OTHER", priority=0, live=()):
        pool = FakePool(live)
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


# --- profile files --------------------------------------------------------


def test_profile_file_is_read_as_a_mapping(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("isolation: exclusive_physical\nscheduler: FIFO\n")

    assert claim_mod._load_profile_file(str(path)) == {
        "isolation": "exclusive_physical", "scheduler": "FIFO",
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
        "priority": 0, "kind": "",
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

    claim("sv", isolation="exclusive_physical", scheduler="FIFO", priority=90, target_pid=1)

    assert state["specs"] == [{
        "name": "claim", "isolation": "exclusive_physical", "scheduler": "FIFO",
        "priority": 90,
    }]


def test_claim_takes_its_settings_from_a_profile(allocator, run_calls, tmp_path):
    state = allocator()
    path = tmp_path / "p.yaml"
    path.write_text("isolation: exclusive_physical\nscheduler: FIFO\npriority: 80\n")

    claim("sv", profile_path=str(path), target_pid=1)

    assert state["specs"][0]["isolation"] == "exclusive_physical"
    assert state["specs"][0]["scheduler"] == "FIFO"
    assert state["specs"][0]["priority"] == 80


def test_claim_keeps_its_arguments_when_the_profile_is_silent(
    allocator, run_calls, tmp_path
):
    state = allocator()
    path = tmp_path / "p.yaml"
    path.write_text("priority: 80\n")

    claim("sv", isolation="exclusive_physical", profile_path=str(path),
          target_pid=1)

    assert state["specs"][0]["isolation"] == "exclusive_physical"


def test_claim_pins_and_schedules_the_target(allocator, run_calls):
    allocator(cpus=(4, 5), scheduler="FIFO", priority=90)

    claim("sv", target_pid=4242)

    assert run_calls == [
        ["taskset", "-a", "-cp", "4-5", "4242"],
        ["chrt", "-a", "-f", "-p", "90", "4242"],
    ]


def test_claim_can_register_without_touching_the_process(allocator, run_calls):
    allocator(cpus=(4,))

    claim("sv", target_pid=4242, no_apply=True)

    assert run_calls == []


def test_claim_without_cores_still_applies_an_rt_policy(allocator, run_calls):
    """isolation=none + FIFO: default affinity, but the RT policy is honoured."""
    allocator(cpus=(), scheduler="FIFO", priority=10)

    claim("sv", target_pid=4242)

    assert run_calls == [["chrt", "-a", "-f", "-p", "10", "4242"]]


def test_claim_without_cores_and_without_rt_touches_nothing(allocator, run_calls):
    allocator(cpus=(), scheduler="OTHER")

    claim("sv", target_pid=4242)

    assert run_calls == []


def test_claim_falls_back_to_other_for_an_unknown_scheduler(allocator, run_calls):
    allocator(cpus=(4,), scheduler="DEADLINE", priority=0)

    claim("sv", target_pid=4242)

    assert run_calls[1] == ["chrt", "-a", "-o", "-p", "0", "4242"]


def test_a_label_held_by_another_live_process_is_refused(allocator, run_calls):
    allocator(live=[{"label": "sv", "pid": 999, "cores": [4]}])

    with pytest.raises(claim_mod.ClaimError, match="held by live pid 999"):
        claim("sv", target_pid=4242)


def test_the_same_process_may_claim_its_label_again(allocator, run_calls):
    state = allocator(live=[{"label": "sv", "pid": 4242, "cores": [4]}])

    claim("sv", target_pid=4242)

    assert state["pool"].claims[0]["label"] == "sv"


@pytest.mark.parametrize("failing", ["taskset", "chrt"])
def test_a_claim_that_cannot_be_applied_is_withdrawn(allocator, monkeypatch,
                                                      failing):
    state = allocator(cpus=(4,), scheduler="FIFO", priority=90)

    def fake_run(cmd, **kwargs):
        rc = 1 if cmd[0] == failing else 0
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="denied")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(claim_mod.ClaimError, match="denied"):
        claim("sv", target_pid=4242)
    assert state["pool"].removed == ["sv"]


def test_a_tool_that_hangs_is_a_claim_error(allocator, monkeypatch):
    allocator(cpus=(4,))

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(claim_mod.ClaimError):
        claim("sv", target_pid=4242)


def test_claim_allocation_returns_what_was_applied(allocator, run_calls):
    # After a hard fallback the allocator drops FIFO to OTHER: the caller
    # must apply that, not its own request.
    allocator(cpus=(0, 1), scheduler="OTHER", priority=0)

    alloc = claim_mod.claim_allocation("sv", scheduler="FIFO", priority=90,
                                       target_pid=4242, no_apply=True)

    assert (alloc.cpus, alloc.scheduler, alloc.priority) == ([0, 1], "OTHER", 0)


def test_a_profile_file_is_validated(allocator, run_calls, tmp_path):
    state = allocator()
    path = tmp_path / "p.yaml"
    path.write_text("isolation: exclusive_logical\nscheduler: fifo\n")

    claim("sv", profile_path=str(path), target_pid=1)

    assert state["specs"][0]["scheduler"] == "FIFO"
    assert state["specs"][0]["priority"] == 1


@pytest.mark.parametrize("scheduler, priority, message", [
    ("FIFO", 0, "within 1-99"),
    ("RR", 150, "within 1-99"),
    ("DEADLINE", 1, "unknown scheduler"),
    ("FIFO", "high", "must be an integer"),
    ("OTHER", 5, "OTHER priority must be 0"),
    ("BATCH", 1, "BATCH priority must be 0"),
])
def test_a_command_line_policy_chrt_would_refuse_is_an_error(
        allocator, run_calls, scheduler, priority, message):
    state = allocator()

    with pytest.raises(claim_mod.ClaimError, match=message):
        claim("sv", scheduler=scheduler, priority=priority, target_pid=1)

    assert "specs" not in state
    assert run_calls == []


def test_a_command_line_isolation_the_allocator_does_not_know_is_an_error(
        allocator, run_calls):
    state = allocator()

    with pytest.raises(claim_mod.ClaimError, match="unknown isolation"):
        claim("sv", isolation="exclusive-logical", scheduler="FIFO",
              priority=80, target_pid=1)

    assert "specs" not in state
    assert run_calls == []


def test_a_command_line_policy_is_normalised(allocator, run_calls):
    state = allocator()

    claim("sv", scheduler="fifo", priority="10", target_pid=1)

    assert state["specs"][0]["scheduler"] == "FIFO"
    assert state["specs"][0]["priority"] == 10


# --- release --------------------------------------------------------------


@pytest.fixture
def releaser(monkeypatch):
    """Replace the pool release() works on."""

    def install(live=()):
        pool = FakePool(live)
        monkeypatch.setattr(claim_mod, "CorePool", lambda **kw: pool)
        return pool

    return install


def test_release_removes_the_claim(releaser):
    pool = releaser(live=[{"label": "sv", "pid": 4242}])

    assert release("sv") is True
    assert pool.removed == ["sv"]


def test_release_of_an_unknown_label_removes_nothing(releaser):
    pool = releaser(live=[{"label": "other", "pid": 4242}])

    assert release("sv") is False
    assert pool.removed == []


def test_release_by_pid_leaves_a_label_taken_over(releaser, caplog):
    pool = releaser(live=[{"label": "sv", "pid": 999}])

    assert release("sv", pid=4242) is False
    assert pool.removed == []
    assert "belongs to another process" in caplog.text


def test_release_by_pid_removes_its_own_claim(releaser):
    pool = releaser(live=[{"label": "sv", "pid": 4242}])

    assert release("sv", pid=4242) is True
    assert pool.removed == ["sv"]


def test_release_moves_no_other_thread(releaser, monkeypatch):
    # Even under repacking: moving live RT threads is left to an explicit
    # `seapath-alloc spread`.
    monkeypatch.setattr("seapath_alloc.config.load_strategy",
                        lambda: AllocationStrategy.REPACKING)
    monkeypatch.setattr(
        "seapath_alloc.repacker.execute_repack",
        lambda *a, **kw: pytest.fail("release must not repack"),
    )
    releaser(live=[{"label": "sv", "pid": 4242}])

    assert release("sv") is True


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
