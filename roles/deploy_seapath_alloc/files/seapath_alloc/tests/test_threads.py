# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import os

import pytest

from seapath_alloc import threads as threads_mod
from seapath_alloc.threads import _classify_threads, discover, find_qemu_pid
from .conftest import make_proc_qemu


class FakeClock:
    """
    Deterministic stand-in for the time module.

    discover() polls /proc with sleeps between rounds; driving the clock from
    the sleeps keeps the tests instant and makes the timeout reachable.
    """

    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.slept = []
        self._on_sleep = on_sleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        if self._on_sleep:
            self._on_sleep(len(self.slept))


@pytest.fixture
def clock(monkeypatch):
    def install(on_sleep=None):
        fake = FakeClock(on_sleep)
        monkeypatch.setattr(threads_mod, "time", fake)
        return fake

    return install


def add_thread(proc, pid, tid, comm):
    """Add one task directory to an existing fake /proc tree."""
    d = os.path.join(proc, str(pid), "task", str(tid))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "comm"), "w") as f:
        f.write(comm + "\n")


# --- find_qemu_pid --------------------------------------------------------


def test_find_qemu_pid_found(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    assert find_qemu_pid("vm", proc) == 1000


def test_find_qemu_pid_absent(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="other", vcpu_count=1)
    assert find_qemu_pid("vm", proc) is None


def test_find_qemu_pid_no_prefix_collision(tmp_path):
    """"guest=vm" must not match the process of VM "vm2"."""
    proc = make_proc_qemu(tmp_path, pid=2000, vm_name="vm2", vcpu_count=1)
    assert find_qemu_pid("vm", proc) is None


def test_find_qemu_pid_two_vms_sharing_prefix(tmp_path):
    make_proc_qemu(tmp_path, pid=2000, vm_name="vm2", vcpu_count=1)
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    assert find_qemu_pid("vm", proc) == 1000
    assert find_qemu_pid("vm2", proc) == 2000


def test_find_qemu_pid_skips_processes_that_are_not_qemu(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    other = tmp_path / "proc" / "999"
    other.mkdir(parents=True)
    (other / "cmdline").write_bytes(b"/usr/bin/sleep\x00guest=vm\x00")

    assert find_qemu_pid("vm", proc) == 1000


def test_find_qemu_pid_skips_a_process_that_exited(tmp_path):
    # A PID directory with no readable cmdline: the process died between the
    # glob and the read, which happens constantly on a busy hypervisor.
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    (tmp_path / "proc" / "999").mkdir(parents=True)

    assert find_qemu_pid("vm", proc) == 1000


def test_find_qemu_pid_on_an_empty_proc(tmp_path):
    empty = tmp_path / "proc"
    empty.mkdir()

    assert find_qemu_pid("vm", str(empty)) is None


# --- _classify_threads ----------------------------------------------------


def test_classify_sorts_each_thread_class(tmp_path):
    proc = make_proc_qemu(
        tmp_path, pid=1000, vm_name="vm", vcpu_count=3,
        vhost_count=2, iothread_count=1,
    )

    threads = _classify_threads(1000, proc)

    assert threads.pid == 1000
    assert threads.emulator_tid == 1000
    assert threads.vcpu_tids == [1010, 1011, 1012]
    assert threads.vhost_tids == [1020, 1021]
    assert threads.iothread_tids == [1030]


def test_classify_ignores_unrelated_threads(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    add_thread(proc, 1000, 1099, "worker")

    threads = _classify_threads(1000, proc)

    assert threads.vcpu_tids == [1010]
    assert 1099 not in threads.vhost_tids + threads.iothread_tids


def test_classify_ignores_a_non_numeric_task_entry(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    os.makedirs(os.path.join(proc, "1000", "task", "notanumber"))

    assert _classify_threads(1000, proc).vcpu_tids == [1010]


def test_classify_skips_a_thread_that_exited(tmp_path):
    # Task directory with no comm file: the thread is gone.
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    os.makedirs(os.path.join(proc, "1000", "task", "1050"))

    assert _classify_threads(1000, proc).vcpu_tids == [1010]


def test_classify_of_a_process_with_no_task_directory(tmp_path):
    proc = tmp_path / "proc"
    (proc / "1000").mkdir(parents=True)

    threads = _classify_threads(1000, str(proc))

    assert threads.vcpu_tids == []
    assert threads.emulator_tid == 1000


# --- discover -------------------------------------------------------------


def test_discover_returns_none_when_the_vm_has_no_process(tmp_path, caplog):
    proc = tmp_path / "proc"
    proc.mkdir()

    with caplog.at_level("WARNING", logger=threads_mod.log.name):
        assert discover("vm", proc_path=str(proc)) is None

    assert "no QEMU process for VM vm" in caplog.text


def test_discover_returns_the_threads_once_all_vcpus_are_up(tmp_path, clock):
    clock()
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=2)

    threads = discover("vm", expected_vcpus=2, proc_path=proc)

    assert threads.vcpu_tids == [1010, 1011]


def test_discover_stops_early_once_the_vhost_count_is_stable(tmp_path, clock):
    fake = clock()
    proc = make_proc_qemu(
        tmp_path, pid=1000, vm_name="vm", vcpu_count=1, vhost_count=2
    )

    threads = discover("vm", expected_vcpus=1, proc_path=proc)

    assert threads.vhost_tids == [1020, 1021]
    # One grace round is enough when the vhost threads are already there.
    assert fake.slept == [0.1]


def test_discover_uses_the_whole_grace_window_without_vhost(tmp_path, clock):
    fake = clock()
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)

    threads = discover("vm", expected_vcpus=1, proc_path=proc)

    assert threads.vhost_tids == []
    assert sum(fake.slept) == pytest.approx(0.5)


def test_discover_waits_for_a_late_vcpu_thread(tmp_path, clock):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)

    def spawn_second_vcpu(round_number):
        if round_number == 2:
            add_thread(proc, 1000, 1011, "CPU 1/KVM")

    clock(on_sleep=spawn_second_vcpu)

    threads = discover("vm", expected_vcpus=2, proc_path=proc)

    assert threads.vcpu_tids == [1010, 1011]


def test_discover_gives_up_on_missing_vcpus_after_the_timeout(
    tmp_path, clock, caplog
):
    fake = clock()
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)

    with caplog.at_level("WARNING", logger=threads_mod.log.name):
        threads = discover("vm", expected_vcpus=4, proc_path=proc, timeout=1.0)

    # Degraded rather than fatal: the VM still gets pinned on what is visible.
    assert threads.vcpu_tids == [1010]
    assert "1/4 vCPU threads visible after 1.0s" in caplog.text
    assert fake.now >= 1.0
