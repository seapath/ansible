# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from seapath_alloc import cli
from seapath_alloc.cli import main


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch):
    """main() configures the root logger on every call; keep it out of the way."""
    monkeypatch.setattr(cli, "setup_logging", lambda *a, **kw: None)


@pytest.fixture
def status(monkeypatch):
    """Serve a canned collect() payload to the status subcommand."""
    def install(**overrides):
        data = {
            "isolated": "4-11",
            "free_logical": "8-11",
            "free_physical": "4",
            "actors": [],
        }
        data.update(overrides)
        monkeypatch.setattr(cli, "collect", lambda: data)
        return data

    return install


# --- status ---------------------------------------------------------------


def test_status_is_the_default_subcommand(status, capsys):
    status()

    main([])

    assert "Isolated: 4-11" in capsys.readouterr().out


def test_status_prints_the_pool_summary(status, capsys):
    status()

    main(["status"])

    out = capsys.readouterr().out
    assert "Isolated: 4-11" in out
    assert "Free logical: 8-11" in out
    assert "Free physical pairs: 4" in out
    # Nothing running: no actor or slot section at all.
    assert "Active actors" not in out
    assert "Slots:" not in out


def test_status_json_dumps_the_raw_payload(status, capsys):
    data = status()

    main(["status", "--json"])

    assert json.loads(capsys.readouterr().out) == data


def test_status_lists_the_threads_of_a_vm(status, capsys):
    status(actors=[{
        "type": "vm", "label": "vm0",
        "threads": [
            {"comm": "CPU 0/KVM", "cpus": "4", "scheduler": "FIFO",
             "priority": 90},
            {"comm": "vhost-1000", "cpus": "5"},
        ],
    }])

    main(["status"])

    out = capsys.readouterr().out
    assert "VM vm0:" in out
    assert "CPU 0/KVM" in out and "cpus=4  FIFO/90" in out
    # No scheduler recorded: nothing is printed rather than a bare slash.
    assert "cpus=5\n" in out


def test_status_lists_a_vm_with_no_threads(status, capsys):
    status(actors=[{"type": "vm", "label": "vm0"}])

    main(["status"])

    assert "VM vm0:" in capsys.readouterr().out


def test_status_lists_nic_irqs(status, capsys):
    status(actors=[{"type": "irq", "label": "eth0:42", "cpus": "6"}])

    main(["status"])

    assert "IRQ eth0:42" in capsys.readouterr().out


def test_status_lists_other_actors_with_their_pid(status, capsys):
    status(actors=[
        {"type": "container", "label": "redis", "cpus": "7", "pid": 4242,
         "scheduler": "FIFO", "priority": 10},
        {"type": "process", "label": "sv", "cpus": "8", "pid": 4243},
    ])

    main(["status"])

    out = capsys.readouterr().out
    assert "container redis" in out and "pid=4242  FIFO/10" in out
    assert "process sv" in out and "pid=4243" in out


# --- claim and release ----------------------------------------------------


def test_claim_prints_the_cores_it_got(monkeypatch, capsys):
    monkeypatch.setattr("seapath_alloc.claim.claim", lambda **kw: [4, 5])

    main(["claim", "--label", "sv"])

    assert capsys.readouterr().out == "4-5\n"


def test_claim_requires_a_label():
    with pytest.raises(SystemExit):
        main(["claim"])


def test_release_forwards_the_label(monkeypatch):
    released = []
    monkeypatch.setattr("seapath_alloc.claim.release", released.append)

    main(["release", "--label", "sv"])

    assert released == ["sv"]


# --- spread ---------------------------------------------------------------


class FakePool:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def bust_cache(self):
        self.busted = True


@pytest.fixture
def pool(monkeypatch):
    """Stand in for CorePool wherever a subcommand opens one."""
    fake = FakePool()
    monkeypatch.setattr("seapath_alloc.pool.CorePool", lambda **kw: fake)
    monkeypatch.setattr("seapath_alloc.topology.Topology", lambda **kw: object())
    return fake


@pytest.fixture
def spread(monkeypatch, pool):
    """Wire find_spread_moves/execute_repack and report what was applied."""
    applied = []

    def install(moves):
        monkeypatch.setattr(
            "seapath_alloc.repacker.find_spread_moves", lambda p: moves
        )
        monkeypatch.setattr(
            "seapath_alloc.repacker.execute_repack",
            lambda m, pool=None: applied.append(m),
        )
        return applied

    return install


def thread_move(tids=(4242,), from_cpu=4, to_cpu=8):
    from seapath_alloc.repacker import ThreadMove
    return ThreadMove(tids=list(tids), from_cpu=from_cpu, to_cpu=to_cpu)


def cgroup_move(label="redis", from_cpu=5, to_cpu=9):
    from seapath_alloc.repacker import CgroupMove
    return CgroupMove(label=label, service="redis.service",
                      from_cpu=from_cpu, to_cpu=to_cpu)


def test_spread_says_so_when_there_is_nothing_to_do(spread, capsys):
    applied = spread([])

    main(["spread"])

    assert "nothing to do" in capsys.readouterr().out
    assert applied == []


def test_spread_dry_run_lists_the_moves_without_applying(spread, capsys):
    applied = spread([thread_move(), cgroup_move()])

    main(["spread", "--dry-run"])

    out = capsys.readouterr().out
    assert "2 move(s) planned (dry-run, not applied)" in out
    assert "tids 4242" in out
    assert "redis" in out
    assert "cpu4 → cpu8" in out
    assert applied == []


def test_spread_applies_the_moves_and_busts_the_cache(spread, pool, capsys):
    moves = [thread_move()]
    applied = spread(moves)

    main(["spread"])

    assert applied == [moves]
    assert pool.busted is True
    assert "applied 1 move(s)" in capsys.readouterr().out


def test_spread_lists_every_tid_sharing_the_donor_core(spread, capsys):
    spread([thread_move(tids=(100, 101, 102))])

    main(["spread", "--dry-run"])

    assert "tids 100,101,102" in capsys.readouterr().out
