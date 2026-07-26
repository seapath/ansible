# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/deploy_seapath_alloc/files/seapath-run."""

import pytest

from support import add_seapath_alloc_to_path, load_script

add_seapath_alloc_to_path()

seapath_run = load_script(
    "roles/deploy_seapath_alloc/files/seapath-run", "seapath_run"
)


class FakeChild:
    """Stand-in for the Popen object seapath-run waits on."""

    def __init__(self, returncode=0, alive=False):
        self.returncode = returncode
        self.alive = alive
        self.waited = False
        self.signals = []

    def poll(self):
        return None if self.alive else self.returncode

    def wait(self):
        self.waited = True
        return self.returncode

    def send_signal(self, signum):
        self.signals.append(signum)


@pytest.fixture
def harness(monkeypatch):
    """
    Drive main() with every out-of-process call replaced.

    Returns a record holding what the script asked of the pool, the signal
    module and subprocess, plus the handlers it installed.
    """
    record = {"claim": None, "released": [], "handlers": {}, "child": None,
              "popen_hook": None}

    monkeypatch.setattr(seapath_run, "setup_logging", lambda: None)

    def fake_claim(**kwargs):
        record["claim"] = kwargs
        return record.get("cores", [4])

    def fake_release(label):
        record["released"].append(label)

    def fake_signal(signum, handler):
        record["handlers"][signum] = handler

    def fake_popen(cmd):
        record["cmd"] = cmd
        # Called while main() is still between "handler installed" and
        # "child assigned", which is where a signal can find no child.
        if record["popen_hook"]:
            record["popen_hook"]()
        return record["child"]

    monkeypatch.setattr(seapath_run, "claim", fake_claim)
    monkeypatch.setattr(seapath_run, "release", fake_release)
    monkeypatch.setattr(seapath_run.signal, "signal", fake_signal)
    monkeypatch.setattr(seapath_run.subprocess, "Popen", fake_popen)

    def run(argv, child=None, cores=None, popen_hook=None):
        record["child"] = child if child is not None else FakeChild()
        if cores is not None:
            record["cores"] = cores
        record["popen_hook"] = popen_hook
        monkeypatch.setattr(seapath_run.sys, "argv", ["seapath-run"] + argv)
        with pytest.raises(SystemExit) as exc:
            seapath_run.main()
        record["exit"] = exc.value.code
        return record

    # Exposed so a test can reach the installed handlers from inside a hook,
    # before run() has returned the record.
    run.record = record
    return run


# --- argument parsing -------------------------------------------------------

def test_parse_args_splits_own_arguments_from_the_command():
    label, isolation, scheduler, priority, cmd = seapath_run._parse_args(
        ["seapath-run", "sv", "exclusive_logical", "fifo", "80",
         "--", "/usr/bin/sv-sim", "-i", "eth0"]
    )

    assert (label, isolation, priority) == ("sv", "exclusive_logical", 80)
    # The scheduler is normalised so "fifo" and "FIFO" behave the same.
    assert scheduler == "FIFO"
    assert cmd == ["/usr/bin/sv-sim", "-i", "eth0"]


def test_parse_args_keeps_a_command_argument_that_looks_like_a_separator():
    _, _, _, _, cmd = seapath_run._parse_args(
        ["seapath-run", "sv", "none", "OTHER", "0", "--", "sh", "-c", "--"]
    )

    assert cmd == ["sh", "-c", "--"]


def test_parse_args_rejects_a_missing_separator(capsys):
    with pytest.raises(SystemExit) as exc:
        seapath_run._parse_args(["seapath-run", "sv", "none", "OTHER", "0"])

    assert exc.value.code == 1
    assert "missing '--' separator" in capsys.readouterr().err


def test_parse_args_rejects_a_wrong_argument_count(capsys):
    with pytest.raises(SystemExit) as exc:
        seapath_run._parse_args(["seapath-run", "sv", "none", "--", "true"])

    assert exc.value.code == 1
    assert "expected 4 arguments before '--', got 2" in capsys.readouterr().err


def test_parse_args_rejects_an_empty_command(capsys):
    with pytest.raises(SystemExit) as exc:
        seapath_run._parse_args(
            ["seapath-run", "sv", "none", "OTHER", "0", "--"]
        )

    assert exc.value.code == 1
    assert "no command specified" in capsys.readouterr().err


def test_parse_args_rejects_a_non_integer_priority(capsys):
    with pytest.raises(SystemExit) as exc:
        seapath_run._parse_args(
            ["seapath-run", "sv", "none", "OTHER", "high", "--", "true"]
        )

    assert exc.value.code == 1
    assert "priority must be an integer, got 'high'" in capsys.readouterr().err


# --- main -------------------------------------------------------------------

def test_main_claims_cores_then_runs_the_command(harness, capsys):
    record = harness(
        ["sv", "exclusive_logical", "FIFO", "80", "--", "/usr/bin/sv-sim"]
    )

    assert record["claim"] == {
        "label": "sv",
        "isolation": "exclusive_logical",
        "scheduler": "FIFO",
        "priority": 80,
        # target_pid 0 means "this process"; the child inherits the affinity
        # and the scheduling policy through fork/exec.
        "target_pid": 0,
        "no_apply": False,
        "kind": "run",
    }
    assert record["cmd"] == ["/usr/bin/sv-sim"]
    assert record["child"].waited
    assert record["exit"] == 0
    err = capsys.readouterr().err
    assert "claimed core(s) 4 for 'sv' (FIFO/80)" in err


def test_main_reports_an_allocation_failure(harness, monkeypatch, capsys):
    def boom(**_kwargs):
        raise RuntimeError("no free isolated core")

    monkeypatch.setattr(seapath_run, "claim", boom)

    record = harness(["sv", "exclusive_logical", "FIFO", "80", "--", "true"])

    assert record["exit"] == 1
    assert "allocation failed: no free isolated core" in capsys.readouterr().err
    # Nothing was claimed, so nothing must be released.
    assert record["released"] == []


def test_main_releases_the_claim_and_mirrors_the_exit_code(harness):
    record = harness(
        ["sv", "none", "OTHER", "0", "--", "false"],
        child=FakeChild(returncode=3),
    )

    assert record["released"] == ["sv"]
    assert record["exit"] == 3


def test_main_reports_a_signalled_child_as_128_plus_signal(harness):
    # subprocess reports a process killed by SIGKILL as returncode -9.
    record = harness(
        ["sv", "none", "OTHER", "0", "--", "sleep"],
        child=FakeChild(returncode=-9),
    )

    assert record["exit"] == 137


def test_main_releases_the_claim_when_the_command_cannot_start(
        harness, monkeypatch, capsys):
    def boom(_cmd):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(seapath_run.subprocess, "Popen", boom)
    monkeypatch.setattr(seapath_run.sys, "argv",
                        ["seapath-run", "sv", "none", "OTHER", "0",
                         "--", "/nope"])
    monkeypatch.setattr(seapath_run, "setup_logging", lambda: None)

    released = []
    monkeypatch.setattr(seapath_run, "release", released.append)
    monkeypatch.setattr(seapath_run, "claim", lambda **_kwargs: [4])
    monkeypatch.setattr(seapath_run.signal, "signal", lambda *_a: None)

    with pytest.raises(FileNotFoundError):
        seapath_run.main()

    assert released == ["sv"]
    assert "released claim for 'sv'" in capsys.readouterr().err


# --- signal forwarding ------------------------------------------------------

def test_main_forwards_signals_to_a_running_child(harness):
    import signal as signal_module

    child = FakeChild(alive=True)
    record = harness(["sv", "none", "OTHER", "0", "--", "sleep"], child=child)

    assert set(record["handlers"]) == {signal_module.SIGTERM,
                                       signal_module.SIGINT}
    record["handlers"][signal_module.SIGTERM](signal_module.SIGTERM, None)

    assert child.signals == [signal_module.SIGTERM]


def test_main_drops_a_signal_once_the_child_has_exited(harness):
    import signal as signal_module

    child = FakeChild(returncode=0, alive=False)
    record = harness(["sv", "none", "OTHER", "0", "--", "true"], child=child)
    record["handlers"][signal_module.SIGINT](signal_module.SIGINT, None)

    assert child.signals == []


def test_main_drops_a_signal_that_arrives_before_the_child_exists(harness):
    import signal as signal_module

    child = FakeChild(alive=True)

    def fire():
        # The handlers are installed before Popen returns, so this runs while
        # the script's "child" is still None.
        handler = harness.record["handlers"][signal_module.SIGTERM]
        handler(signal_module.SIGTERM, None)

    harness(["sv", "none", "OTHER", "0", "--", "sleep"],
            child=child, popen_hook=fire)

    assert child.signals == []


def test_main_ignores_a_child_that_disappears_while_being_signalled(harness):
    import signal as signal_module

    class VanishingChild(FakeChild):
        def send_signal(self, signum):
            raise ProcessLookupError

    child = VanishingChild(alive=True)
    record = harness(["sv", "none", "OTHER", "0", "--", "sleep"], child=child)

    record["handlers"][signal_module.SIGTERM](signal_module.SIGTERM, None)
