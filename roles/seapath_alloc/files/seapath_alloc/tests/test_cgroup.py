# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import os
import subprocess

import pytest

from seapath_alloc import cgroup
from seapath_alloc.cgroup import (
    cgroup_procs,
    cgroup_root,
    cgroup_threads,
    place_service,
    schedule_payload,
    service_cgroups,
    set_affinity,
    set_policy,
)


@pytest.fixture
def sched(monkeypatch):
    """
    Stand in for sched_setaffinity and sched_setscheduler.

    ``calls`` records (kind, tid, value) in order; a tid listed in ``gone``
    raises ProcessLookupError, one in ``denied`` PermissionError.
    """
    state = {"calls": [], "gone": set(), "denied": set()}

    def check(tid):
        if tid in state["gone"]:
            raise ProcessLookupError(3, "No such process")
        if tid in state["denied"]:
            raise PermissionError(1, "Operation not permitted")

    def setaffinity(tid, cpus):
        check(tid)
        state["calls"].append(("affinity", tid, sorted(cpus)))

    def setscheduler(tid, policy, param):
        check(tid)
        state["calls"].append(("policy", tid, (policy, param)))

    monkeypatch.setattr(os, "sched_setaffinity", setaffinity, raising=False)
    monkeypatch.setattr(os, "sched_setscheduler", setscheduler, raising=False)
    monkeypatch.setattr(os, "sched_param", lambda prio: prio, raising=False)
    return state


@pytest.fixture
def systemctl(monkeypatch):
    def install(output=None, fail=False):
        def fake_check_output(cmd, **kwargs):
            if fail:
                raise subprocess.CalledProcessError(1, cmd)
            return output

        monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    return install


def make_tree(root, procs=None, cpuset=False, threads=None):
    """Create a cgroup directory, optionally with procs, threads and a cpuset knob."""
    root.mkdir(parents=True, exist_ok=True)
    if procs is not None:
        (root / "cgroup.procs").write_text(procs)
    if threads is not None:
        (root / "cgroup.threads").write_text(
            "".join(f"{t}\n" for t in threads))
    if cpuset:
        (root / "cpuset.cpus").write_text("")
    return root


PAYLOAD = "libpod-payload-0123abcd"


def make_quadlet(tmp_path, payload_threads=(200, 201, 202), conmon=(100,)):
    """
    The tree quadlet's podman run --cgroups=split produces: an empty service
    root, systemd's .control, conmon in runtime/, the container in its
    libpod-payload sub-cgroup.
    """
    root = make_tree(tmp_path / "sv.service", threads=(), cpuset=True)
    make_tree(root / ".control", threads=(), cpuset=True)
    make_tree(root / "runtime", threads=conmon, cpuset=True)
    make_tree(root / PAYLOAD, threads=payload_threads, cpuset=True)
    return root


def cpusets(root):
    """{relative dir: cpuset.cpus} over the tree."""
    out = {}
    for dirpath, _d, files in os.walk(root):
        if "cpuset.cpus" in files:
            rel = os.path.relpath(dirpath, root)
            out[rel] = open(os.path.join(dirpath, "cpuset.cpus")).read()
    return out


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


# --- cgroup_threads -------------------------------------------------------


def test_cgroup_threads_lists_every_thread_not_only_processes(tmp_path):
    # cgroup.procs would give 200 alone; the other threads are what chrt -p
    # used to miss.
    d = make_tree(tmp_path / "p", procs="200\n", threads=(200, 201, 202))

    assert cgroup_threads([str(d)]) == [200, 201, 202]


def test_cgroup_threads_skips_a_vanished_cgroup(tmp_path):
    d = make_tree(tmp_path / "p", threads=(200,))

    assert cgroup_threads([str(tmp_path / "gone"), str(d)]) == [200]


# --- service_cgroups -------------------------------------------------------


def test_service_cgroups_separates_the_payload_from_conmon(tmp_path):
    root = make_quadlet(tmp_path)
    nested = make_tree(root / PAYLOAD / "inner")

    payload, rest = service_cgroups(str(root))

    assert payload == [str(root / PAYLOAD), str(nested)]
    assert rest == [str(root / ".control"), str(root / "runtime")]


def test_service_cgroups_without_a_payload(tmp_path):
    root = make_tree(tmp_path / "sv.service")
    make_tree(root / "child")

    assert service_cgroups(str(root)) == ([], [str(root / "child")])


# --- set_affinity / set_policy --------------------------------------------


def test_set_affinity_pins_every_thread(sched):
    set_affinity([200, 201], [6])

    assert sched["calls"] == [("affinity", 200, [6]), ("affinity", 201, [6])]


def test_set_affinity_skips_a_vanished_thread_and_logs_a_refusal(
        sched, caplog):
    sched["gone"].add(200)
    sched["denied"].add(201)

    with caplog.at_level("WARNING", logger=cgroup.log.name):
        set_affinity([200, 201, 202], [6])

    assert sched["calls"] == [("affinity", 202, [6])]
    assert "affinity 6 on thread 201" in caplog.text
    assert "thread 200" not in caplog.text


@pytest.mark.parametrize(
    "scheduler,policy",
    [("FIFO", os.SCHED_FIFO), ("RR", os.SCHED_RR), ("OTHER", os.SCHED_OTHER),
     ("BATCH", cgroup.SCHED_POLICY["BATCH"])],
)
def test_set_policy_maps_the_scheduler(sched, scheduler, policy):
    set_policy([200], scheduler, 42)

    assert sched["calls"] == [("policy", 200, (policy, 42))]


def test_set_policy_falls_back_to_other_for_an_unknown_scheduler(sched):
    set_policy([200], "DEADLINE", 0)

    assert sched["calls"] == [("policy", 200, (os.SCHED_OTHER, 0))]


def test_set_policy_skips_a_vanished_thread_and_logs_a_refusal(sched, caplog):
    sched["gone"].add(200)
    sched["denied"].add(201)

    with caplog.at_level("WARNING", logger=cgroup.log.name):
        set_policy([200, 201, 202], "FIFO", 50)

    assert [c[1] for c in sched["calls"]] == [202]
    assert "policy FIFO/50 on thread 201" in caplog.text


# --- place_service ----------------------------------------------------------


def test_place_service_splits_payload_and_housekeeping(tmp_path, sched):
    root = make_quadlet(tmp_path)

    place_service(str(root), [6], [0, 1, 2, 3])

    assert cpusets(root) == {
        ".": "0-3,6",
        ".control": "0-3",
        "runtime": "0-3",
        PAYLOAD: "6",
    }
    assert sched["calls"] == [
        ("affinity", 200, [6]), ("affinity", 201, [6]), ("affinity", 202, [6]),
        ("affinity", 100, [0, 1, 2, 3]),
    ]


def test_place_service_grows_the_root_before_narrowing_the_payload(
        tmp_path, sched, monkeypatch):
    # A move from 6 to 8: while the payload is rewritten, its parent must
    # already hold 8, or the payload falls back to the parent's whole set.
    root = make_quadlet(tmp_path)
    (root / "cpuset.cpus").write_text("0-3,6")
    writes = []
    real = cgroup._write_cpuset

    def spy(d, cpus):
        writes.append((os.path.relpath(d, root), cpus))
        real(d, cpus)

    monkeypatch.setattr(cgroup, "_write_cpuset", spy)

    place_service(str(root), [8], [0, 1, 2, 3])

    assert writes == [
        (".", "0-3,6,8"),
        (PAYLOAD, "8"),
        (".control", "0-3"),
        ("runtime", "0-3"),
        (".", "0-3,8"),
    ]


def test_place_service_without_a_payload_pins_the_whole_tree(tmp_path, sched):
    root = make_tree(tmp_path / "sv.service", threads=(100, 101), cpuset=True)
    make_tree(root / "child", threads=(200,), cpuset=True)

    place_service(str(root), [6, 7], [0, 1])

    assert cpusets(root) == {".": "6-7", "child": "6-7"}
    assert [c[1] for c in sched["calls"]] == [100, 101, 200]


def test_place_service_without_housekeeping_pins_the_whole_tree(
        tmp_path, sched):
    root = make_quadlet(tmp_path)

    place_service(str(root), [6], [])

    assert set(cpusets(root).values()) == {"6"}
    assert ("affinity", 100, [6]) in sched["calls"]


def test_place_service_survives_a_vanished_sub_cgroup(
        tmp_path, sched, caplog, monkeypatch):
    # The container can exit mid-walk: the write fails, the rest goes on.
    root = make_quadlet(tmp_path)
    real_open = open

    def refuse(path, *args, **kwargs):
        if "runtime" in str(path) and "w" in args:
            raise FileNotFoundError(2, "No such file or directory")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)

    with caplog.at_level("WARNING", logger=cgroup.log.name):
        place_service(str(root), [6], [0, 1, 2, 3])

    assert "runtime" in caplog.text
    assert cpusets(root)[PAYLOAD] == "6"


def test_place_service_on_an_unreadable_root_cpuset(tmp_path, sched):
    root = make_quadlet(tmp_path)
    (root / "cpuset.cpus").unlink()

    place_service(str(root), [6], [0, 1])

    assert cpusets(root)["."] == "0-1,6"


# --- schedule_payload -------------------------------------------------------


def test_schedule_payload_leaves_conmon_alone(tmp_path, sched):
    root = make_quadlet(tmp_path)

    done = schedule_payload(str(root), "FIFO", 50)

    assert done == [200, 201, 202]
    assert [c[1] for c in sched["calls"]] == [200, 201, 202]


def test_schedule_payload_covers_the_whole_tree_without_a_payload(
        tmp_path, sched):
    root = make_tree(tmp_path / "sv.service", threads=(100,))
    make_tree(root / "child", threads=(200, 201))

    assert schedule_payload(str(root), "RR", 10) == [100, 200, 201]


def test_schedule_payload_catches_threads_started_meanwhile(
        tmp_path, sched, monkeypatch):
    # A thread spawned by a thread not yet switched inherits SCHED_OTHER: the
    # next pass picks it up, and threads already done are not redone.
    root = make_quadlet(tmp_path, payload_threads=(200,))
    reads = iter([[200], [200, 201], [200, 201]])
    monkeypatch.setattr(cgroup, "cgroup_threads", lambda dirs: next(reads))

    assert schedule_payload(str(root), "FIFO", 50) == [200, 201]
    assert [c[1] for c in sched["calls"]] == [200, 201]


def test_schedule_payload_gives_up_after_a_few_passes(
        tmp_path, sched, monkeypatch):
    root = make_quadlet(tmp_path)
    counter = iter(range(1000, 2000))
    monkeypatch.setattr(cgroup, "cgroup_threads",
                        lambda dirs: [next(counter)])

    assert len(schedule_payload(str(root), "FIFO", 50)) == cgroup.POLICY_PASSES
