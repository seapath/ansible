# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Tests for CorePool's claim bookkeeping and its /proc scanners, in particular
the paths taken when a process or a file disappears mid-scan.

Topology: isolated 4-11, pairs (4,5)(6,7)(8,9)(10,11), housekeeping 0-3.
"""

import os

import pytest

from seapath_alloc.pool import CorePool
from seapath_alloc.topology import Topology
from .conftest import make_cpu_topology, make_proc_irq, make_sys_nic_irqs

ISOLATED = set(range(4, 12))
# Claims are expired on read once their PID is gone from /proc, so a claim
# that has to survive needs its PID present in the fake tree.
CLAIM_PID = 4242


@pytest.fixture
def pool(tmp_path):
    """An unlocked pool over an empty fake /proc and /sys."""
    sys_p = make_cpu_topology(tmp_path)
    proc_path = str(tmp_path / "proc")
    os.makedirs(os.path.join(proc_path, str(CLAIM_PID)), exist_ok=True)
    return CorePool(
        topology=Topology(sys_cpu_path=sys_p),
        proc_path=proc_path,
        sys_path=str(tmp_path / "sys"),
        alloc_dir=str(tmp_path / "alloc"),
    )


def write_status(proc, pid, tid, comm, cpus="4", extra=""):
    d = os.path.join(proc, str(pid), "task", str(tid))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "status"), "w") as f:
        f.write(f"Name:\t{comm}\n{extra}Cpus_allowed_list:\t{cpus}\n")
    return d


# --- context manager ------------------------------------------------------


def test_the_pool_is_a_context_manager(pool):
    with pool as entered:
        assert entered is pool
        assert pool._lock_fd is not None

    assert pool._lock_fd is None


def test_topology_is_exposed(pool):
    assert pool.topology().isolated_cpus() == sorted(ISOLATED)


# --- claim bookkeeping ----------------------------------------------------


def test_a_claim_records_its_kind_and_slot(pool):
    with pool:
        pool.add_claim("redis", CLAIM_PID, [4], "FIFO", 10,
                       kind="quadlet", slot="rt")

        claim = pool.all_claims()[0]

    assert claim["kind"] == "quadlet"
    assert claim["slot"] == "rt"


def test_a_claim_without_a_kind_or_slot_omits_them(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)

        claim = pool.all_claims()[0]

    assert "kind" not in claim
    assert "slot" not in claim


def test_moving_a_claim_reassigns_its_core(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)

        pool.move_claim_cpu("sv", 8)

        assert pool.all_claims()[0]["cores"] == [8]


def test_moving_an_unknown_claim_changes_nothing(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)

        pool.move_claim_cpu("other", 8)

        assert pool.all_claims()[0]["cores"] == [4]


def test_removing_a_claim_frees_its_core(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)
        assert 4 not in pool.free_logical()

        pool.remove_claim("sv")

        assert pool.all_claims() == []
        assert 4 in pool.free_logical()


def test_reserved_siblings_are_dropped_once_the_holder_is_gone(pool):
    with pool:
        pool.add_reserved_sibling(5, 4)

        # Nothing is pinned on cpu4, so the reservation is stale.
        assert pool.active_reserved_siblings() == []


def test_reserved_siblings_survive_while_the_holder_is_pinned(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)
        pool.add_reserved_sibling(5, 4)

        assert pool.active_reserved_siblings() == [(5, 4)]


# --- QEMU scanner ---------------------------------------------------------


def test_qemu_scanner_counts_pinned_threads(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")

    assert pool._busy_by_qemus(ISOLATED) == {4}


def test_qemu_scanner_ignores_unpinned_threads(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="0-11")

    assert pool._busy_by_qemus(ISOLATED) == set()


def test_qemu_scanner_skips_a_thread_that_exited(pool, monkeypatch):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")
    write_status(pool._proc, 2000, 2010, "CPU 0/KVM", cpus="6")
    real_open = open

    def refuse(path, *args, **kwargs):
        if os.sep + "2000" + os.sep in str(path):
            raise OSError("no such process")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)

    assert pool._busy_by_qemus(ISOLATED) == {4}


def test_qemu_scanner_skips_a_status_without_a_name(pool):
    d = os.path.join(pool._proc, "1000", "task", "1010")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Cpus_allowed_list:\t4\n")

    assert pool._busy_by_qemus(ISOLATED) == set()


def test_qemu_scanner_skips_a_status_without_an_affinity(pool):
    d = os.path.join(pool._proc, "1000", "task", "1010")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\n")

    assert pool._busy_by_qemus(ISOLATED) == set()


def test_excluded_pids_are_not_counted_as_busy(pool):
    """Re-pinning a running VM must see its own cores as available."""
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")
    pool.exclude_pids({1000})

    assert pool._busy_by_qemus(ISOLATED) == set()


def test_excluding_a_pid_also_excludes_its_vhost_threads(pool):
    # vhost threads live under their own PID; only their comm ties them back.
    write_status(pool._proc, 3000, 3000, "vhost-1000", cpus="5")
    pool.exclude_pids({1000})

    assert pool._busy_by_qemus(ISOLATED) == set()


def test_a_thread_path_without_a_pid_is_not_excluded(pool):
    # The exclusion reads the PID out of the path; a shape it cannot parse
    # must leave the thread counted rather than silently freeing its core.
    d = os.path.join(pool._proc, "task", "1010")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\nCpus_allowed_list:\t4\n")
    pool.exclude_pids({1000})

    assert pool._thread_excluded(["proc", "task", "1010", "status"],
                                 "CPU 0/KVM") is False


# --- workload thread scanner ----------------------------------------------


def test_workload_scanner_maps_cores_to_their_threads(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")

    assert pool.pinned_workload_threads() == {4: [1010]}


def test_workload_scanner_skips_a_thread_that_exited(pool, monkeypatch):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")
    write_status(pool._proc, 2000, 2010, "CPU 0/KVM", cpus="6")
    real_open = open

    def refuse(path, *args, **kwargs):
        if os.sep + "2000" + os.sep in str(path):
            raise OSError("no such process")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)

    assert pool.pinned_workload_threads() == {4: [1010]}


def test_workload_scanner_skips_a_status_without_a_name(pool):
    d = os.path.join(pool._proc, "1000", "task", "1010")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Cpus_allowed_list:\t4\n")

    assert pool.pinned_workload_threads() == {}


def test_workload_scanner_skips_excluded_threads(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")
    pool.exclude_pids({1000})

    assert pool.pinned_workload_threads() == {}


def test_workload_scanner_ignores_non_workload_threads(pool):
    write_status(pool._proc, 1000, 1010, "sshd", cpus="4")

    assert pool.pinned_workload_threads() == {}


def test_workload_scanner_skips_a_status_without_an_affinity(pool):
    d = os.path.join(pool._proc, "1000", "task", "1010")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\n")

    assert pool.pinned_workload_threads() == {}


def test_workload_scanner_ignores_threads_spanning_several_cores(pool):
    # Repacking moves a whole core; a thread on two cores is not a candidate.
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4-5")

    assert pool.pinned_workload_threads() == {}


def test_workload_scanner_ignores_threads_on_housekeeping(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="1")

    assert pool.pinned_workload_threads() == {}


def test_workload_scanner_includes_a_run_process(pool):
    """seapath-run's children inherit its core and must move with it."""
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0, kind="run")
        write_status(pool._proc, CLAIM_PID, 1010, "worker", cpus="4",
                     extra=f"Tgid:\t{CLAIM_PID}\nPPid:\t1\n")

        assert pool.pinned_workload_threads() == {4: [1010]}


def test_workload_scanner_includes_the_children_of_a_run_process(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0, kind="run")
        write_status(pool._proc, 2000, 2010, "worker", cpus="4",
                     extra=f"Tgid:\t2000\nPPid:\t{CLAIM_PID}\n")

        assert pool.pinned_workload_threads() == {4: [2010]}


def test_workload_scanner_ignores_a_process_unrelated_to_any_run(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0, kind="run")
        write_status(pool._proc, 2000, 2010, "worker", cpus="6",
                     extra="Tgid:\t2000\nPPid:\t1\n")

        assert pool.pinned_workload_threads() == {}


def test_workload_scanner_tolerates_a_status_without_tgid(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0, kind="run")
        write_status(pool._proc, 2000, 2010, "worker", cpus="4")

        assert pool.pinned_workload_threads() == {}


def test_workload_scanner_skips_a_non_numeric_task_path(pool):
    d = os.path.join(pool._proc, "1000", "task", "notatid")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\nCpus_allowed_list:\t4\n")

    assert pool.pinned_workload_threads() == {}


# --- NIC IRQ scanner ------------------------------------------------------


def test_irq_scanner_counts_nic_interrupts_on_isolated_cores(pool, tmp_path):
    make_sys_nic_irqs(tmp_path, [181], iface="eno1", sys_path=pool._sys)
    make_proc_irq(tmp_path, {181: "6"}, proc_path=pool._proc)

    assert pool._busy_by_irqs(ISOLATED) == {6}


def test_irq_scanner_ignores_a_non_numeric_msi_entry(pool, tmp_path):
    make_sys_nic_irqs(tmp_path, [181], iface="eno1", sys_path=pool._sys)
    open(os.path.join(pool._sys, "class", "net", "eno1", "device",
                      "msi_irqs", "notanirq"), "w").close()
    make_proc_irq(tmp_path, {181: "6"}, proc_path=pool._proc)

    assert pool._busy_by_irqs(ISOLATED) == {6}


def test_irq_scanner_skips_an_interrupt_with_no_affinity_file(pool, tmp_path):
    make_sys_nic_irqs(tmp_path, [181, 182], iface="eno1", sys_path=pool._sys)
    make_proc_irq(tmp_path, {181: "6"}, proc_path=pool._proc)

    assert pool._busy_by_irqs(ISOLATED) == {6}
