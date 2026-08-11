# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/cyclictest/files/run_cyclictest.py."""

import pytest

from support import load_script

run_cyclictest = load_script("roles/cyclictest/files/run_cyclictest.py")


class FakeCompletedProcess:
    def __init__(self, stdout=""):
        self.stdout = stdout


@pytest.fixture
def fake_run(monkeypatch):
    def install(stdout=""):
        recorded = {}

        def _run(argv, **kwargs):
            recorded["argv"] = argv
            recorded["kwargs"] = kwargs
            return FakeCompletedProcess(stdout)

        monkeypatch.setattr(run_cyclictest.subprocess, "run", _run)
        return recorded

    return install


def test_parse_args_defaults():
    args = run_cyclictest.parse_args(["/tmp/out.txt"])

    assert args.output_file == "/tmp/out.txt"
    assert args.duration == 20
    assert args.priority == 90
    assert args.affinity == "smp"


def test_parse_args_reads_every_option():
    args = run_cyclictest.parse_args(
        ["/tmp/out.txt", "-d", "60", "-p", "80", "-a", "2-5"]
    )

    assert args.duration == 60
    assert args.priority == 80
    assert args.affinity == "2-5"


def test_parse_args_accepts_a_bare_affinity_flag():
    # -a without a value means "pin the threads, let cyclictest choose".
    args = run_cyclictest.parse_args(["/tmp/out.txt", "-a"])

    assert args.affinity == ""


def test_parse_args_requires_an_output_file():
    with pytest.raises(SystemExit):
        run_cyclictest.parse_args([])


def test_build_command_defaults_to_the_smp_flag():
    args = run_cyclictest.parse_args(["/tmp/out.txt"])

    assert run_cyclictest.build_command(args) == (
        "cyclictest -l100000 -m -S -p90 -i200 -h400 -q"
    )


def test_build_command_pins_the_threads_when_given_an_affinity():
    args = run_cyclictest.parse_args(["/tmp/out.txt", "-a", "2-5"])

    assert "-a 2-5 -t" in run_cyclictest.build_command(args)
    assert "-S" not in run_cyclictest.build_command(args)


def test_build_command_treats_a_bare_affinity_as_non_smp():
    args = run_cyclictest.parse_args(["/tmp/out.txt", "-a"])

    assert "-a  -t" in run_cyclictest.build_command(args)


def test_build_command_derives_the_cycle_count_from_the_duration():
    args = run_cyclictest.parse_args(["/tmp/out.txt", "-d", "1"])

    # One second at a 200 us interval is 5000 cycles.
    assert "-l5000 " in run_cyclictest.build_command(args)


def test_build_command_carries_the_priority():
    args = run_cyclictest.parse_args(["/tmp/out.txt", "-p", "42"])

    assert "-p42" in run_cyclictest.build_command(args)


def test_main_writes_the_command_then_its_output(fake_run, tmp_path):
    fake_run("T: 0 histogram\n")
    output = tmp_path / "result.txt"

    run_cyclictest.main([str(output)])

    assert output.read_text() == (
        "cyclictest -l100000 -m -S -p90 -i200 -h400 -qT: 0 histogram\n"
    )


def test_main_runs_cyclictest_with_the_built_argument_list(fake_run, tmp_path):
    recorded = fake_run()

    run_cyclictest.main([str(tmp_path / "result.txt"), "-a", "2-5"])

    assert recorded["argv"][0] == "cyclictest"
    assert "-a" in recorded["argv"]
    assert "2-5" in recorded["argv"]
    assert recorded["kwargs"]["capture_output"] is True
    assert recorded["kwargs"]["text"] is True


def test_main_announces_the_command(fake_run, tmp_path, capsys):
    fake_run()

    run_cyclictest.main([str(tmp_path / "result.txt")])

    assert "Will run command: cyclictest" in capsys.readouterr().out
