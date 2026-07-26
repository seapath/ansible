# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for the live data collection half of status.py."""

import os

import pytest

from seapath_alloc import status as status_mod
from seapath_alloc.status import (
    _read_irq_actors,
    _read_qemu_actors,
    _read_sched,
    collect,
)
from .conftest import (
    make_cpu_topology,
    make_proc_irq,
    make_proc_qemu,
    make_sys_nic_irqs,
)

ISOLATED = set(range(4, 12))


def write_stat(proc, pid, tid, policy=0, rt_priority=0, comm="CPU 0/KVM"):
    """
    Add a /proc/<pid>/task/<tid>/stat file.

    _read_sched() skips past the parenthesised comm and then indexes the
    remaining fields, so only positions 37 (rt_priority) and 38 (policy)
    have to carry anything.
    """
    fields = ["0"] * 39
    fields[0] = "S"
    fields[37] = str(rt_priority)
    fields[38] = str(policy)
    path = os.path.join(proc, str(pid), "task", str(tid), "stat")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{tid} ({comm}) " + " ".join(fields) + "\n")
    return path


# --- _read_sched ----------------------------------------------------------


@pytest.mark.parametrize(
    "policy,name",
    [(0, "OTHER"), (1, "FIFO"), (2, "RR"), (3, "BATCH"), (5, "IDLE"),
     (6, "DEADLINE")],
)
def test_read_sched_names_the_policy(tmp_path, policy, name):
    path = write_stat(str(tmp_path), 1000, 1010, policy=policy, rt_priority=90)

    assert _read_sched(path) == (name, 90)


def test_read_sched_reports_an_unknown_policy(tmp_path):
    path = write_stat(str(tmp_path), 1000, 1010, policy=42)

    assert _read_sched(path) == ("?", 0)


def test_read_sched_handles_a_comm_containing_parentheses(tmp_path):
    path = write_stat(str(tmp_path), 1000, 1010, policy=1, rt_priority=80,
                      comm="worker (2)")

    assert _read_sched(path) == ("FIFO", 80)


def test_read_sched_of_a_thread_that_exited(tmp_path):
    assert _read_sched(str(tmp_path / "absent")) == ("", 0)


def test_read_sched_of_a_truncated_stat_file(tmp_path):
    path = tmp_path / "stat"
    path.write_text("1010 (CPU 0/KVM) S 1 2 3\n")

    assert _read_sched(str(path)) == ("", 0)


def test_read_sched_of_a_stat_file_with_garbage(tmp_path):
    path = tmp_path / "stat"
    path.write_text("1010 (CPU 0/KVM) " + " ".join(["x"] * 39) + "\n")

    assert _read_sched(str(path)) == ("", 0)


# --- _read_qemu_actors ----------------------------------------------------


def test_qemu_actors_group_threads_by_vm(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=2,
                          vcpu_cpus=[4, 5], emulator_cpu=6)

    actors = _read_qemu_actors(proc, ISOLATED)

    assert len(actors) == 1
    assert actors[0]["type"] == "vm"
    assert actors[0]["label"] == "vm0"
    assert sorted(t["cpus"] for t in actors[0]["threads"]) == ["4", "5", "6"]


def test_qemu_actors_ignore_unpinned_threads(tmp_path):
    # An unpinned thread is allowed on housekeeping cores too, so it is not
    # consuming the isolated pool and must not show up as an actor.
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=2)

    assert _read_qemu_actors(proc, ISOLATED) == []


def test_qemu_actors_ignore_non_qemu_threads(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=1,
                          vcpu_cpus=[4])
    other = os.path.join(proc, "2000", "task", "2000")
    os.makedirs(other)
    with open(os.path.join(other, "status"), "w") as f:
        f.write("Name:\tsshd\nCpus_allowed_list:\t4\n")

    actors = _read_qemu_actors(proc, ISOLATED)

    assert [a["label"] for a in actors] == ["vm0"]


def test_qemu_actors_skip_a_status_file_without_a_name(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=1,
                          vcpu_cpus=[4])
    broken = os.path.join(proc, "2000", "task", "2000")
    os.makedirs(broken)
    with open(os.path.join(broken, "status"), "w") as f:
        f.write("Cpus_allowed_list:\t4\n")

    assert len(_read_qemu_actors(proc, ISOLATED)) == 1


def test_qemu_actors_skip_a_status_file_without_an_affinity(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=1,
                          vcpu_cpus=[4])
    broken = os.path.join(proc, "2000", "task", "2000")
    os.makedirs(broken)
    with open(os.path.join(broken, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\n")

    assert len(_read_qemu_actors(proc, ISOLATED)) == 1


def test_qemu_actors_skip_a_thread_that_exited(tmp_path, monkeypatch):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=1,
                          vcpu_cpus=[4])
    gone = os.path.join(proc, "2000", "task", "2000")
    os.makedirs(gone)
    with open(os.path.join(gone, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\nCpus_allowed_list:\t4\n")
    real_open = open

    def refuse(path, *args, **kwargs):
        if os.sep + "2000" + os.sep in str(path):
            raise OSError("no such process")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)

    assert len(_read_qemu_actors(proc, ISOLATED)) == 1


def test_qemu_actors_attribute_vhost_threads_to_their_vm(tmp_path):
    """
    vhost threads are kernel threads with an empty cmdline; their comm
    carries the QEMU PID, which is how they are traced back to the VM.
    """
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=1,
                          vhost_count=1, vcpu_cpus=[4], vhost_cpus=[5])

    actors = _read_qemu_actors(proc, ISOLATED)

    assert len(actors) == 1
    comms = sorted(t["comm"] for t in actors[0]["threads"])
    assert comms == ["CPU 0/KVM", "vhost-1000"]


def test_qemu_actors_fall_back_to_the_pid_without_a_vm_name(tmp_path):
    proc = str(tmp_path / "proc")
    task = os.path.join(proc, "1000", "task", "1010")
    os.makedirs(task)
    with open(os.path.join(task, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\nCpus_allowed_list:\t4\n")

    actors = _read_qemu_actors(proc, ISOLATED)

    assert actors[0]["label"] == "pid-1000"


def test_qemu_actors_fall_back_to_the_pid_when_the_cmdline_has_no_guest(tmp_path):
    proc = str(tmp_path / "proc")
    task = os.path.join(proc, "1000", "task", "1010")
    os.makedirs(task)
    with open(os.path.join(task, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\nCpus_allowed_list:\t4\n")
    with open(os.path.join(proc, "1000", "cmdline"), "wb") as f:
        f.write(b"/usr/bin/qemu-system-x86_64\x00-m\x002048\x00")

    actors = _read_qemu_actors(proc, ISOLATED)

    assert actors[0]["label"] == "pid-1000"


def test_qemu_actors_report_the_scheduler_of_each_thread(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=1,
                          vcpu_cpus=[4], emulator_cpu=5)
    write_stat(proc, 1000, 1010, policy=1, rt_priority=90)

    actors = _read_qemu_actors(proc, ISOLATED)

    vcpu = [t for t in actors[0]["threads"] if t["comm"] == "CPU 0/KVM"][0]
    assert (vcpu["scheduler"], vcpu["priority"]) == ("FIFO", 90)


# --- _read_irq_actors -----------------------------------------------------


def test_irq_actors_report_nic_interrupts_on_isolated_cores(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181, 182], iface="eno1")
    proc = make_proc_irq(tmp_path, {181: "6", 182: "7"})

    actors = _read_irq_actors(proc, ISOLATED, sys_path=sys_path)

    assert [(a["label"], a["cpus"]) for a in actors] == [
        ("eno1/181", "6"), ("eno1/182", "7"),
    ]


def test_irq_actors_collapse_interrupts_sharing_a_cpu(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181, 182, 183], iface="eno1")
    proc = make_proc_irq(tmp_path, {181: "6", 182: "6", 183: "6"})

    actors = _read_irq_actors(proc, ISOLATED, sys_path=sys_path)

    assert len(actors) == 1
    assert actors[0]["irqs"] == "181-183"
    assert actors[0]["label"] == "eno1/181-183"
    assert actors[0]["iface"] == "eno1"


def test_irq_actors_split_a_multiqueue_nic_by_cpu(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181, 182, 183], iface="eno1")
    proc = make_proc_irq(tmp_path, {181: "6", 182: "6", 183: "7"})

    actors = _read_irq_actors(proc, ISOLATED, sys_path=sys_path)

    assert [(a["irqs"], a["cpus"]) for a in actors] == [("181-182", "6"),
                                                        ("183", "7")]


def test_irq_actors_sort_by_interface(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181], iface="eth1")
    make_sys_nic_irqs(tmp_path, [190], iface="eno1", sys_path=sys_path)
    proc = make_proc_irq(tmp_path, {181: "6", 190: "7"})

    actors = _read_irq_actors(proc, ISOLATED, sys_path=sys_path)

    assert [a["iface"] for a in actors] == ["eno1", "eth1"]


def test_irq_actors_ignore_interrupts_on_housekeeping_cores(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181], iface="eno1")
    proc = make_proc_irq(tmp_path, {181: "0-3"})

    assert _read_irq_actors(proc, ISOLATED, sys_path=sys_path) == []


def test_irq_actors_keep_only_the_isolated_part_of_an_affinity(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181], iface="eno1")
    proc = make_proc_irq(tmp_path, {181: "2-6"})

    actors = _read_irq_actors(proc, ISOLATED, sys_path=sys_path)

    assert actors[0]["cpus"] == "4-6"


def test_irq_actors_ignore_a_non_numeric_msi_entry(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181], iface="eno1")
    open(os.path.join(sys_path, "class", "net", "eno1", "device",
                      "msi_irqs", "notanirq"), "w").close()
    proc = make_proc_irq(tmp_path, {181: "6"})

    assert len(_read_irq_actors(proc, ISOLATED, sys_path=sys_path)) == 1


def test_irq_actors_skip_an_interrupt_with_no_affinity_file(tmp_path):
    sys_path = make_sys_nic_irqs(tmp_path, [181, 182], iface="eno1")
    proc = make_proc_irq(tmp_path, {181: "6"})

    actors = _read_irq_actors(proc, ISOLATED, sys_path=sys_path)

    assert [a["irqs"] for a in actors] == ["181"]


def test_irq_actors_on_a_host_with_no_nic(tmp_path):
    proc = str(tmp_path / "proc")
    os.makedirs(proc, exist_ok=True)

    assert _read_irq_actors(proc, ISOLATED, sys_path=str(tmp_path)) == []


# --- collect --------------------------------------------------------------


@pytest.fixture
def node(tmp_path, monkeypatch):
    """A fake node: cpu topology, a pinned VM, a NIC IRQ and a claim."""
    sys_path = make_cpu_topology(tmp_path)
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm0", vcpu_count=1,
                          vcpu_cpus=[4], emulator_cpu=5)
    make_sys_nic_irqs(tmp_path, [181], iface="eno1",
                      sys_path=str(tmp_path / "sys"))
    make_proc_irq(tmp_path, {181: "6"}, proc_path=proc)
    monkeypatch.setattr(
        status_mod, "Topology", lambda **kw: _Topology(sys_path)
    )
    return proc, str(tmp_path / "sys")


class _Topology:
    def __init__(self, sys_cpu_path):
        from seapath_alloc.topology import Topology
        self._real = Topology(sys_cpu_path=sys_cpu_path)

    def __getattr__(self, name):
        return getattr(self._real, name)


class FakePool:
    def __init__(self, claims=()):
        self._claims = list(claims)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def free_logical(self):
        return [8, 9, 10, 11]

    def free_physical(self):
        return [8, 10]

    def all_claims(self):
        return self._claims

    def active_reserved_siblings(self):
        return [(5, 4)]



def test_collect_reports_the_pool_state(node, monkeypatch):
    proc, sys_path = node
    monkeypatch.setattr(status_mod, "CorePool", lambda **kw: FakePool())

    data = collect(proc_path=proc, sys_path=sys_path)

    assert data["isolated"] == "4-11"
    assert data["free_logical"] == "8-11"
    assert data["free_physical"] == "8,10"


def test_collect_merges_vm_irq_and_claim_actors(node, monkeypatch):
    proc, sys_path = node
    monkeypatch.setattr(
        status_mod, "CorePool",
        lambda **kw: FakePool(claims=[{
            "label": "sv", "pid": 4242, "cores": [7],
            "scheduler": "FIFO", "priority": 80,
        }]),
    )

    data = collect(proc_path=proc, sys_path=sys_path)

    by_type = {a["type"]: a for a in data["actors"]}
    assert by_type["vm"]["label"] == "vm0"
    assert by_type["irq"]["label"] == "eno1/181"
    assert by_type["claim"]["label"] == "sv"
    assert by_type["claim"]["cpus"] == "7"
    assert by_type["claim"]["pid"] == 4242


