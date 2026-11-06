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


def test_status_lists_degraded_actors_with_their_reason(status, capsys):
    status(fallbacks=[{
        "label": "VM debian14", "group": "vcpu/1",
        "requested": "exclusive_phyical", "severity": "hard",
        "reason": "unknown isolation 'exclusive_phyical', no RT isolation",
    }])

    main(["status"])

    out = capsys.readouterr().out
    assert "Degraded:" in out
    assert "hard  VM debian14  vcpu/1" in out
    assert "unknown isolation 'exclusive_phyical'" in out


def test_status_omits_the_degraded_section_when_all_is_well(status, capsys):
    status(fallbacks=[])

    main(["status"])

    assert "Degraded" not in capsys.readouterr().out


# --- claim and release ----------------------------------------------------


def _granted(cpus=(4, 5), severity="", warning="", **kw):
    """A GroupAllocation as claim_allocation() returns it."""
    from seapath_alloc.allocator import GroupAllocation
    return GroupAllocation(name="claim", cpus=list(cpus),
                           scheduler=kw.get("scheduler", "FIFO"),
                           priority=kw.get("priority", 80),
                           severity=severity, warning=warning)


def test_claim_prints_the_cores_it_got(monkeypatch, capsys):
    monkeypatch.setattr("seapath_alloc.claim.claim_allocation",
                        lambda **kw: _granted())

    main(["claim", "--label", "sv", "--target-pid", "777"])

    out = capsys.readouterr()
    assert out.out == "4-5\n"
    assert out.err == ""


@pytest.mark.parametrize("argv", [
    ["--isolation", "slot:sv0"],
    ["--isolation", "slot:sv0", "--slot", "sv0"],
])
def test_claim_takes_the_slot_from_the_isolation(monkeypatch, argv):
    seen = {}
    monkeypatch.setattr("seapath_alloc.claim.claim_allocation",
                        lambda **kw: seen.update(kw) or _granted(cpus=(14,)))

    main(["claim", "--label", "sv", "--target-pid", "777"] + argv)

    assert seen["slot"] == "sv0"
    assert seen["isolation"] == "exclusive_logical"


def test_claim_refuses_two_different_slots(monkeypatch, capsys):
    monkeypatch.setattr("seapath_alloc.claim.claim_allocation",
                        lambda **kw: _granted(cpus=(14,)))

    with pytest.raises(SystemExit) as excinfo:
        main(["claim", "--label", "sv", "--target-pid", "777",
              "--isolation", "slot:a", "--slot", "b"])

    assert excinfo.value.code == 1
    assert "different slots" in capsys.readouterr().err


def test_claim_passes_every_option_through(monkeypatch, capsys):
    seen = {}

    def fake_claim(**kwargs):
        seen.update(kwargs)
        return _granted(cpus=(7,))

    monkeypatch.setattr("seapath_alloc.claim.claim_allocation", fake_claim)

    main([
        "claim", "--label", "sv", "--isolation", "exclusive_physical",
        "--scheduler", "FIFO", "--priority", "90", "--profile", "/etc/p.yaml",
        "--target-pid", "4242", "--no-apply", "--slot", "rt",
    ])

    assert seen == {
        "label": "sv", "isolation": "exclusive_physical", "scheduler": "FIFO",
        "priority": 90, "profile_path": "/etc/p.yaml", "target_pid": 4242,
        "no_apply": True, "slot": "rt", "count": 1,
    }


def test_claim_defaults(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "seapath_alloc.claim.claim_allocation",
        lambda **kw: (seen.update(kw), _granted())[1],
    )

    main(["claim", "--label", "sv", "--target-pid", "777"])

    assert seen["isolation"] == "exclusive_logical"
    assert seen["scheduler"] == "OTHER"
    assert seen["priority"] == 0
    assert seen["no_apply"] is False


def test_claim_belongs_to_the_pid_it_is_given(monkeypatch):
    seen = {}
    monkeypatch.setattr("seapath_alloc.claim.claim_allocation",
                        lambda **kw: (seen.update(kw), _granted())[1])

    main(["claim", "--label", "sv", "--target-pid", "777"])

    assert seen["target_pid"] == 777


def test_claim_requires_an_owner(capsys):
    # Under sudo the parent of this command is sudo itself, which exits at
    # once: there is no default owner.
    with pytest.raises(SystemExit) as excinfo:
        main(["claim", "--label", "sv"])

    assert excinfo.value.code == 2
    assert "--target-pid" in capsys.readouterr().err


def test_claim_parses_a_core_count(monkeypatch):
    seen = {}
    monkeypatch.setattr("seapath_alloc.claim.claim_allocation",
                        lambda **kw: (seen.update(kw), _granted())[1])

    main(["claim", "--label", "sv", "--target-pid", "777",
          "--isolation", "exclusive_logical:2"])

    assert (seen["isolation"], seen["count"]) == ("exclusive_logical", 2)


@pytest.mark.parametrize("isolation", ["exclusive_logical:0", None])
def test_claim_reports_an_error_and_exits_1(monkeypatch, capsys, isolation):
    from seapath_alloc.claim import ClaimError

    def refuse(**kw):
        raise ClaimError("label 'sv' is held by live pid 9")

    monkeypatch.setattr("seapath_alloc.claim.claim_allocation", refuse)
    argv = ["claim", "--label", "sv", "--target-pid", "777"]
    if isolation:
        argv += ["--isolation", isolation]

    with pytest.raises(SystemExit) as excinfo:
        main(argv)

    assert excinfo.value.code == 1
    assert "seapath-alloc claim:" in capsys.readouterr().err


def test_claim_warns_about_a_degraded_allocation(monkeypatch, capsys):
    monkeypatch.setattr(
        "seapath_alloc.claim.claim_allocation",
        lambda **kw: _granted(cpus=(5,), severity="soft",
                              warning="HT sibling not reserved"))

    main(["claim", "--label", "sv", "--isolation", "exclusive_physical",
          "--target-pid", "777"])

    out = capsys.readouterr()
    assert out.out == "5\n"
    assert "warning: HT sibling not reserved" in out.err


def test_claim_refuses_an_rt_request_the_pool_cannot_isolate(monkeypatch,
                                                              capsys):
    released = []
    monkeypatch.setattr(
        "seapath_alloc.claim.claim_allocation",
        lambda **kw: _granted(cpus=(0, 1), severity="hard", scheduler="OTHER",
                              priority=0, warning="no free isolated core"))
    monkeypatch.setattr("seapath_alloc.claim.release",
                        lambda label, pid=0: released.append((label, pid)))

    with pytest.raises(SystemExit) as excinfo:
        main(["claim", "--label", "sv", "--scheduler", "fifo",
              "--priority", "80", "--target-pid", "777"])

    assert excinfo.value.code == 1
    assert released == [("sv", 777)]
    out = capsys.readouterr()
    assert out.out == ""
    assert "no isolated core for 'sv'" in out.err


class ClaimsPool:
    def __init__(self, claims):
        self.claims = claims

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def all_claims(self):
        return self.claims


@pytest.fixture
def releaser(monkeypatch):
    def install(claims, removed=True):
        released = []
        monkeypatch.setattr("seapath_alloc.pool.CorePool",
                            lambda **kw: ClaimsPool(claims))
        monkeypatch.setattr("seapath_alloc.claim.release",
                            lambda label: released.append(label) or removed)
        return released

    return install


def test_release_removes_a_claim_without_an_owner(releaser):
    released = releaser([{"label": "sv", "pid": 0}])

    main(["release", "--label", "sv"])

    assert released == ["sv"]


def test_release_refuses_a_claim_whose_owner_runs(releaser, capsys):
    released = releaser([{"label": "sv", "pid": 4242}])

    with pytest.raises(SystemExit) as excinfo:
        main(["release", "--label", "sv"])

    assert excinfo.value.code == 1
    assert released == []
    assert "held by live pid 4242" in capsys.readouterr().err


def test_release_force_removes_a_claim_whose_owner_runs(releaser):
    released = releaser([{"label": "sv", "pid": 4242}])

    main(["release", "--label", "sv", "--force"])

    assert released == ["sv"]


def test_release_of_an_unknown_label_exits_1(releaser, capsys):
    released = releaser([{"label": "other", "pid": 0}])

    with pytest.raises(SystemExit) as excinfo:
        main(["release", "--label", "sv"])

    assert excinfo.value.code == 1
    assert released == []
    assert "no claim 'sv'" in capsys.readouterr().err


def test_release_of_a_claim_gone_meanwhile_exits_1(releaser, capsys):
    releaser([{"label": "sv", "pid": 0}], removed=False)

    with pytest.raises(SystemExit) as excinfo:
        main(["release", "--label", "sv"])

    assert excinfo.value.code == 1
    assert "no claim 'sv'" in capsys.readouterr().err


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

    main(["slot", "rt", "--cpus", "10", "--isolation", "exclusive_physical"])

    assert seen["isolation"] == "exclusive_physical"


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
