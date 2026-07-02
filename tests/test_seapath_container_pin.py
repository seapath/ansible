# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/seapath_alloc/files/seapath-container-pin."""

import subprocess

import pytest

from support import add_seapath_alloc_to_path, load_script

add_seapath_alloc_to_path()

pin = load_script(
    "roles/seapath_alloc/files/seapath-container-pin",
    "seapath_container_pin",
)


@pytest.fixture
def harness(monkeypatch):
    """
    Drive main() with the pool, the cgroup helpers and systemd replaced.

    ``record`` holds the claim keyword arguments and every cgroup write the
    script attempted, in order.
    """
    record = {"claim": None, "cpuset": [], "chrt": []}

    monkeypatch.setattr(pin, "setup_logging", lambda: None)

    def fake_claim(**kwargs):
        record["claim"] = kwargs
        return record["cores"]

    monkeypatch.setattr(pin, "claim", fake_claim)
    monkeypatch.setattr(pin, "place_service",
                        lambda root, cpus, hk: record["cpuset"].append((root, cpus, hk)))
    monkeypatch.setattr(pin, "schedule_payload",
                        lambda root, sched, prio: record["chrt"].append((root, sched, prio)))

    class FakeTopology:
        def housekeeping_cpus(self):
            return [0, 1, 2, 3]

    monkeypatch.setattr(pin, "Topology", FakeTopology)

    def run(argv, cores=(4,), root="/sys/fs/cgroup/system.slice/sv.service",
            main_pid=1234, cgroup_pids=(1234,)):
        record["cores"] = list(cores)
        monkeypatch.setattr(pin, "cgroup_root", lambda service: root)
        monkeypatch.setattr(pin, "cgroup_procs", lambda r: list(cgroup_pids))
        monkeypatch.setattr(pin, "_service_main_pid", lambda service: main_pid)
        monkeypatch.setattr(pin.sys, "argv", ["seapath-container-pin"] + argv)
        try:
            pin.main()
        except SystemExit as exc:
            record["exit"] = exc.code
        else:
            record["exit"] = 0
        return record

    return run


# --- MainPID lookup ---------------------------------------------------------

def test_service_main_pid_returns_the_systemd_main_pid(monkeypatch):
    seen = {}

    def fake_check_output(argv, **kwargs):
        seen["argv"] = argv
        return "4242\n"

    monkeypatch.setattr(pin.subprocess, "check_output", fake_check_output)

    assert pin._service_main_pid("sv.service") == 4242
    assert seen["argv"] == ["systemctl", "show", "--property=MainPID",
                            "--value", "sv.service"]


@pytest.mark.parametrize("value", ["0", "1"])
def test_service_main_pid_rejects_a_pid_that_owns_nothing(monkeypatch, value):
    # 0 is "no main process"; 1 is systemd itself, which would keep the claim
    # alive forever.
    monkeypatch.setattr(pin.subprocess, "check_output", lambda *a, **k: value)

    assert pin._service_main_pid("sv.service") == 0


def test_service_main_pid_survives_a_failed_systemctl(monkeypatch):
    def boom(*_a, **_k):
        raise subprocess.CalledProcessError(1, "systemctl")

    monkeypatch.setattr(pin.subprocess, "check_output", boom)

    assert pin._service_main_pid("sv.service") == 0


def test_service_main_pid_survives_a_non_numeric_answer(monkeypatch):
    monkeypatch.setattr(pin.subprocess, "check_output", lambda *a, **k: "n/a")

    assert pin._service_main_pid("sv.service") == 0


# --- argument handling ------------------------------------------------------

def test_main_rejects_a_wrong_argument_count(harness, capsys):
    record = harness(["sv.service", "exclusive_logical"])

    assert record["exit"] == 1
    assert "usage:" in capsys.readouterr().err


def test_main_rejects_an_empty_slot_name(harness, capsys):
    record = harness(["sv.service", "slot:", "FIFO", "80"])

    assert record["exit"] == 1
    assert "empty slot name" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["sv", "sv.service"])
def test_main_accepts_the_service_name_with_or_without_its_suffix(
        harness, name, capsys):
    record = harness([name, "exclusive_logical", "FIFO", "80"])

    # The claim is labelled with the bare name, the cgroup with the unit name.
    assert record["claim"]["label"] == "sv"
    assert "pinned sv.service to core(s) 4" in capsys.readouterr().out


# --- claim ownership --------------------------------------------------------

def test_main_claims_on_behalf_of_the_container_main_pid(harness):
    record = harness(["sv.service", "slot:sv0", "FIFO", "80"], main_pid=4242)

    assert record["claim"] == {
        "label": "sv",
        "isolation": "exclusive_logical",
        "scheduler": "FIFO",
        "priority": 80,
        # The claim must be keyed on the container PID: keyed on this
        # short-lived script it would expire on the next pool read.
        "target_pid": 4242,
        # The cgroup write below replaces the per-process taskset.
        "no_apply": True,
        "kind": "quadlet",
        "slot": "sv0",
    }


def test_main_falls_back_to_the_first_cgroup_pid(harness):
    record = harness(["sv.service", "exclusive_logical", "FIFO", "80"],
                     main_pid=0, cgroup_pids=(999, 1000))

    assert record["claim"]["target_pid"] == 999


def test_main_refuses_to_claim_for_an_empty_cgroup(harness, capsys):
    record = harness(["sv.service", "exclusive_logical", "FIFO", "80"],
                     main_pid=0, cgroup_pids=())

    assert record["exit"] == 1
    assert "no live PID found" in capsys.readouterr().err
    assert record["claim"] is None


def test_main_refuses_to_claim_without_a_cgroup(harness, capsys):
    record = harness(["sv.service", "exclusive_logical", "FIFO", "80"],
                     main_pid=0, root=None)

    assert record["exit"] == 1
    assert "no live PID found" in capsys.readouterr().err


# --- cgroup application -----------------------------------------------------

ROOT = "/sys/fs/cgroup/system.slice/sv.service"


def test_main_places_the_service_then_schedules_the_payload(harness):
    record = harness(["sv.service", "exclusive_physical", "FIFO", "80"],
                     cores=(4, 5), cgroup_pids=(1234, 1235))

    assert record["cpuset"] == [(ROOT, [4, 5], [0, 1, 2, 3])]
    assert record["chrt"] == [(ROOT, "FIFO", 80)]


def test_main_lowercase_scheduler_is_normalised(harness):
    record = harness(["sv.service", "exclusive_logical", "fifo", "80"])

    assert record["claim"]["scheduler"] == "FIFO"
    assert record["chrt"] == [(ROOT, "FIFO", 80)]


def test_main_applies_an_rt_policy_without_isolation(harness):
    # isolation=none allocates no core, but the RT priority is still honoured.
    record = harness(["sv.service", "none", "FIFO", "80"], cores=())

    assert record["cpuset"] == []
    assert record["chrt"] == [(ROOT, "FIFO", 80)]


def test_main_touches_nothing_for_a_plain_unisolated_service(harness, capsys):
    record = harness(["sv.service", "none", "OTHER", "0"], cores=())

    assert record["cpuset"] == []
    assert record["chrt"] == []
    assert "pinned sv.service to core(s)  (OTHER/0)" in capsys.readouterr().out


def test_main_skips_the_cgroup_when_the_service_has_none(harness):
    # No cgroup means nothing to write to; the claim is still registered so
    # the cores are not handed to somebody else.
    record = harness(["sv.service", "exclusive_logical", "FIFO", "80"],
                     root=None)

    assert record["claim"]["label"] == "sv"
    assert record["cpuset"] == []
    assert record["chrt"] == []


# --- end to end on a quadlet cgroup tree ------------------------------------

def test_main_on_a_quadlet_tree_leaves_conmon_on_housekeeping(
        tmp_path, monkeypatch, capsys):
    """
    The real cgroup helpers on the tree podman --cgroups=split produces:
    every payload thread, including those started before the pin, gets the
    core and the policy; conmon gets the housekeeping cores and no policy.
    """
    root = tmp_path / "sv.service"
    tree = {
        root: (),
        root / ".control": (),
        root / "runtime": (100,),
        root / "libpod-payload-abc": (200, 201, 202),
    }
    for d, tids in tree.items():
        d.mkdir(parents=True, exist_ok=True)
        (d / "cpuset.cpus").write_text("")
        (d / "cgroup.threads").write_text("".join(f"{t}\n" for t in tids))
        (d / "cgroup.procs").write_text(f"{tids[0]}\n" if tids else "")

    calls = []
    monkeypatch.setattr(pin, "setup_logging", lambda: None)
    monkeypatch.setattr(pin, "claim", lambda **kw: [6])
    monkeypatch.setattr(pin, "cgroup_root", lambda service: str(root))
    monkeypatch.setattr(pin, "_service_main_pid", lambda service: 100)

    class FakeTopology:
        def housekeeping_cpus(self):
            return [0, 1]

    monkeypatch.setattr(pin, "Topology", FakeTopology)
    monkeypatch.setattr(pin.sys, "argv",
                        ["seapath-container-pin", "sv", "exclusive_logical",
                         "FIFO", "50"])
    monkeypatch.setattr("os.sched_setaffinity",
                        lambda tid, cpus: calls.append(("cpus", tid, sorted(cpus))),
                        raising=False)
    monkeypatch.setattr("os.sched_setscheduler",
                        lambda tid, pol, prm: calls.append(("policy", tid, prm)),
                        raising=False)
    monkeypatch.setattr("os.sched_param", lambda prio: prio, raising=False)

    pin.main()

    assert (root / "libpod-payload-abc" / "cpuset.cpus").read_text() == "6"
    assert (root / "runtime" / "cpuset.cpus").read_text() == "0-1"
    assert (root / ".control" / "cpuset.cpus").read_text() == "0-1"
    assert (root / "cpuset.cpus").read_text() == "0-1,6"
    assert calls == [
        ("cpus", 200, [6]), ("cpus", 201, [6]), ("cpus", 202, [6]),
        ("cpus", 100, [0, 1]),
        ("policy", 200, 50), ("policy", 201, 50), ("policy", 202, 50),
    ]
    assert "pinned sv.service to core(s) 6 (FIFO/50)" in capsys.readouterr().out
