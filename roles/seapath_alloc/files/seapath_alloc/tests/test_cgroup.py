# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import subprocess

import pytest

from seapath_alloc import cgroup
from seapath_alloc.cgroup import (
    apply_cpuset,
    cgroup_procs,
    cgroup_root,
    chrt_procs,
    taskset_procs,
)


@pytest.fixture
def run_calls(monkeypatch):
    """Record subprocess.run invocations without running anything."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


@pytest.fixture
def systemctl(monkeypatch):
    def install(output=None, fail=False):
        def fake_check_output(cmd, **kwargs):
            if fail:
                raise subprocess.CalledProcessError(1, cmd)
            return output

        monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    return install


def make_tree(root, procs=None, cpuset=False):
    """Create a cgroup directory, optionally with procs and a cpuset knob."""
    root.mkdir(parents=True, exist_ok=True)
    if procs is not None:
        (root / "cgroup.procs").write_text(procs)
    if cpuset:
        (root / "cpuset.cpus").write_text("")
    return root


# --- cgroup_root ----------------------------------------------------------


def test_cgroup_root_prefixes_the_unified_hierarchy(systemctl):
    systemctl(output="/system.slice/redis.service\n")

    assert cgroup_root("redis.service") == (
        "/sys/fs/cgroup/system.slice/redis.service"
    )


def test_cgroup_root_is_none_for_a_service_with_no_cgroup(systemctl):
    # systemctl answers with an empty value for an inactive unit.
    systemctl(output="\n")

    assert cgroup_root("redis.service") is None


def test_cgroup_root_is_none_when_systemctl_fails(systemctl):
    systemctl(fail=True)

    assert cgroup_root("nosuch.service") is None


# --- cgroup_procs ---------------------------------------------------------


def test_cgroup_procs_collects_the_whole_tree(tmp_path):
    root = make_tree(tmp_path / "svc", procs="100\n101\n")
    make_tree(root / "child", procs="200\n")

    assert sorted(cgroup_procs(str(root))) == [100, 101, 200]


def test_cgroup_procs_ignores_blank_lines(tmp_path):
    root = make_tree(tmp_path / "svc", procs="100\n\n \n101\n")

    assert cgroup_procs(str(root)) == [100, 101]


def test_cgroup_procs_of_an_empty_cgroup(tmp_path):
    root = make_tree(tmp_path / "svc", procs="")

    assert cgroup_procs(str(root)) == []


def test_cgroup_procs_skips_directories_without_the_file(tmp_path):
    root = make_tree(tmp_path / "svc")
    make_tree(root / "child", procs="200\n")

    assert cgroup_procs(str(root)) == [200]


def test_cgroup_procs_survives_an_unreadable_file(tmp_path, monkeypatch):
    # A cgroup can vanish between the walk and the read; the surviving ones
    # must still be reported.
    root = make_tree(tmp_path / "svc", procs="100\n")
    make_tree(root / "gone", procs="200\n")
    real_open = open

    def refuse(path, *args, **kwargs):
        if "gone" in str(path):
            raise OSError("no such file or directory")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)

    assert cgroup_procs(str(root)) == [100]


# --- apply_cpuset ---------------------------------------------------------


def test_apply_cpuset_writes_at_every_level(tmp_path):
    root = make_tree(tmp_path / "svc", cpuset=True)
    child = make_tree(root / "child", cpuset=True)

    apply_cpuset(str(root), "4-5")

    assert (root / "cpuset.cpus").read_text() == "4-5"
    assert (child / "cpuset.cpus").read_text() == "4-5"


def test_apply_cpuset_skips_directories_without_the_knob(tmp_path):
    root = make_tree(tmp_path / "svc")
    child = make_tree(root / "child", cpuset=True)

    apply_cpuset(str(root), "6")

    assert (child / "cpuset.cpus").read_text() == "6"


def test_apply_cpuset_warns_instead_of_raising(tmp_path, caplog, monkeypatch):
    # A cgroup whose cpuset knob refuses the write must not abort the walk:
    # the remaining cgroups still have to be pinned.
    root = make_tree(tmp_path / "svc", cpuset=True)
    real_open = open

    def refuse(path, *args, **kwargs):
        if str(path).endswith("cpuset.cpus"):
            raise OSError("device or resource busy")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)

    with caplog.at_level("WARNING", logger=cgroup.log.name):
        apply_cpuset(str(root), "4-5")

    assert "cpuset" in caplog.text
    assert "device or resource busy" in caplog.text


# --- taskset and chrt -----------------------------------------------------


def test_taskset_procs_pins_every_pid(run_calls):
    taskset_procs([100, 101], "4-5")

    assert run_calls == [
        ["taskset", "-cp", "4-5", "100"],
        ["taskset", "-cp", "4-5", "101"],
    ]


def test_taskset_procs_of_an_empty_list_does_nothing(run_calls):
    taskset_procs([], "4-5")

    assert run_calls == []


@pytest.mark.parametrize(
    "scheduler,flag",
    [("FIFO", "-f"), ("RR", "-r"), ("OTHER", "-o"), ("BATCH", "-b")],
)
def test_chrt_procs_maps_the_scheduler_to_its_flag(run_calls, scheduler, flag):
    chrt_procs([100], scheduler, 42)

    assert run_calls == [["chrt", flag, "-p", "42", "100"]]


def test_chrt_procs_falls_back_to_other_for_an_unknown_scheduler(run_calls):
    chrt_procs([100], "DEADLINE", 0)

    assert run_calls == [["chrt", "-o", "-p", "0", "100"]]


def test_chrt_procs_applies_to_every_pid(run_calls):
    chrt_procs([100, 101], "FIFO", 90)

    assert [c[-1] for c in run_calls] == ["100", "101"]
