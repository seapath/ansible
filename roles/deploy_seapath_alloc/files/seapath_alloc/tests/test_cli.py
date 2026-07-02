# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import json

import pytest

from seapath_alloc import cli
from seapath_alloc.cli import main


class FakePool:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def bust_cache(self):
        self.busted = True


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


@pytest.fixture
def pool(monkeypatch):
    """Stand in for CorePool wherever a subcommand opens one."""
    fake = FakePool()
    monkeypatch.setattr("seapath_alloc.pool.CorePool", lambda **kw: fake)
    monkeypatch.setattr("seapath_alloc.topology.Topology", lambda **kw: object())
    return fake


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


def test_status_lists_slots_with_their_members(status, capsys):
    status(slots=[{
        "name": "rt-shared", "cores": "10", "isolation": "shared",
        "members": [
            {"kind": "vm", "label": "vm0", "group": "vcpu/0", "cpus": "10",
             "scheduler": "FIFO", "priority": 80},
            {"kind": "process", "label": "sv", "group": "claim", "cpus": "10"},
        ],
    }])

    main(["status"])

    out = capsys.readouterr().out
    assert "rt-shared" in out and "isolation=shared" in out
    assert "vm0/vcpu/0" in out and "FIFO/80" in out
    assert "sv/claim" in out


def test_status_reports_slot_warnings(status, capsys):
    status(slots=[{
        "name": "rt-shared", "cores": "10", "isolation": "shared",
        "members": [],
        "warnings": ["cpu10 also carries a NIC IRQ"],
    }])

    main(["status"])

    assert "warning: cpu10 also carries a NIC IRQ" in capsys.readouterr().out


# --- claim and release ----------------------------------------------------


def test_claim_prints_the_cores_it_got(monkeypatch, capsys):
    monkeypatch.setattr("seapath_alloc.claim.claim", lambda **kw: [4, 5])

    main(["claim", "--label", "sv"])

    assert capsys.readouterr().out == "4-5\n"


def test_claim_passes_every_option_through(monkeypatch, capsys):
    seen = {}

    def fake_claim(**kwargs):
        seen.update(kwargs)
        return [7]

    monkeypatch.setattr("seapath_alloc.claim.claim", fake_claim)

    main([
        "claim", "--label", "sv", "--isolation", "shared",
        "--scheduler", "FIFO", "--priority", "90", "--profile", "/etc/p.yaml",
        "--target-pid", "4242", "--no-apply", "--slot", "rt",
    ])

    assert seen == {
        "label": "sv", "isolation": "shared", "scheduler": "FIFO",
        "priority": 90, "profile_path": "/etc/p.yaml", "target_pid": 4242,
        "no_apply": True, "slot": "rt",
    }


def test_claim_defaults(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "seapath_alloc.claim.claim",
        lambda **kw: (seen.update(kw), [])[1],
    )

    main(["claim", "--label", "sv"])

    assert seen["isolation"] == "exclusive_logical"
    assert seen["scheduler"] == "OTHER"
    assert seen["priority"] == 0
    assert seen["no_apply"] is False


def test_claim_requires_a_label():
    with pytest.raises(SystemExit):
        main(["claim"])


def test_release_forwards_the_label(monkeypatch):
    released = []
    monkeypatch.setattr("seapath_alloc.claim.release", released.append)

    main(["release", "--label", "sv"])

    assert released == ["sv"]


# --- slot -----------------------------------------------------------------


def test_slot_declares_the_operator_chosen_cores(monkeypatch, pool, capsys):
    seen = {}

    def fake_declare(pool_arg, cores, name, topo, isolation):
        seen.update(cores=cores, name=name, isolation=isolation)
        return cores

    monkeypatch.setattr("seapath_alloc.scheduler.declare_slot", fake_declare)

    main(["slot", "rt-shared", "--cpus", "7,10-11"])

    assert seen == {"cores": [7, 10, 11], "name": "rt-shared",
                    "isolation": "exclusive_logical"}
    assert capsys.readouterr().out == "7,10-11\n"


def test_slot_records_the_requested_isolation(monkeypatch, pool, capsys):
    seen = {}
    monkeypatch.setattr(
        "seapath_alloc.scheduler.declare_slot",
        lambda p, cores, name, topo, isolation: (
            seen.update(isolation=isolation), cores)[1],
    )

    main(["slot", "rt", "--cpus", "10", "--isolation", "shared"])

    assert seen["isolation"] == "shared"


def test_slot_requires_the_cpu_list():
    with pytest.raises(SystemExit):
        main(["slot", "rt"])


# --- spread ---------------------------------------------------------------


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


# --- export ---------------------------------------------------------------


def test_export_writes_the_prometheus_file(monkeypatch):
    written = []
    monkeypatch.setattr(
        "seapath_alloc.exporter.write_prom", lambda: written.append(True)
    )

    main(["export"])

    assert written == [True]
