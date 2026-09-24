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


def write_stat(directory, comm="x", flags=0, start=1000):
    """A /proc stat line: flags is field 9, start time field 22."""
    fields = ["S", "1"] + ["0"] * 4 + [str(flags)] + ["0"] * 12 + [str(start)]
    with open(os.path.join(directory, "stat"), "w") as f:
        f.write(f"123 ({comm}) " + " ".join(fields) + "\n")


KTHREAD = 0x00200000


# --- context manager ------------------------------------------------------


def test_the_pool_is_a_context_manager(pool):
    with pool as entered:
        assert entered is pool
        assert pool._lock_fd is not None

    assert pool._lock_fd is None


def test_the_lock_can_be_taken_again_by_its_holder(pool):
    with pool:
        fd = pool._lock_fd
        with pool:
            assert pool._lock_fd is fd
        assert pool._lock_fd is fd

    assert pool._lock_fd is None


def test_unlocking_a_pool_that_is_not_locked_does_nothing(pool):
    pool.unlock()

    assert pool._lock_fd is None


def test_a_failed_flock_closes_its_file(pool, monkeypatch):
    def refuse(fd, op):
        raise OSError("interrupted")

    monkeypatch.setattr("seapath_alloc.pool.fcntl.flock", refuse)

    with pytest.raises(OSError):
        pool.lock()
    assert pool._lock_fd is None


def test_topology_is_exposed(pool):
    assert pool.topology().isolated_cpus() == sorted(ISOLATED)


# --- claim bookkeeping ----------------------------------------------------


def test_a_claim_records_its_kind(pool):
    with pool:
        pool.add_claim("redis", CLAIM_PID, [4], "FIFO", 10, kind="quadlet")

        claim = pool.all_claims()[0]

    assert claim["kind"] == "quadlet"


def test_a_claim_without_a_kind_omits_it(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)

        claim = pool.all_claims()[0]

    assert "kind" not in claim


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


def test_a_claim_records_the_start_time_of_its_process(pool):
    write_stat(os.path.join(pool._proc, str(CLAIM_PID)), start=777)
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)

        assert pool.all_claims()[0]["start"] == 777


def test_a_claim_whose_pid_was_reused_lapses(pool):
    stat_dir = os.path.join(pool._proc, str(CLAIM_PID))
    write_stat(stat_dir, start=777)
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)
    # The process died and the PID went to another one.
    write_stat(stat_dir, start=999)
    pool.bust_cache()

    assert pool.all_claims() == []
    assert 4 in pool.free_logical()


def test_a_claim_keeps_its_core_while_its_start_time_matches(pool):
    write_stat(os.path.join(pool._proc, str(CLAIM_PID)), start=777)
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)
    pool.bust_cache()

    assert 4 not in pool.free_logical()


def test_a_claim_without_a_pid_stays_until_removed(pool):
    with pool:
        pool.add_claim("manual", 0, [4], "OTHER", 0)

        assert [c["label"] for c in pool.all_claims()] == ["manual"]
        assert "start" not in pool.all_claims()[0]


def test_saving_leaves_no_temporary_file(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)

    assert sorted(os.listdir(pool._alloc_dir)) == [".lock", "claims.json"]


def test_reserved_siblings_survive_while_the_holder_is_pinned(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0)
        pool.add_reserved_sibling(5, 4)

        assert pool.active_reserved_siblings() == [(5, 4)]


# --- pinned thread scanner ------------------------------------------------


def test_qemu_scanner_counts_pinned_threads(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")

    assert pool._busy_by_threads(ISOLATED) == {4}


def test_qemu_scanner_ignores_unpinned_threads(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="0-11")

    assert pool._busy_by_threads(ISOLATED) == set()


def test_qemu_scanner_skips_a_thread_that_exited(pool, monkeypatch):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")
    write_status(pool._proc, 2000, 2010, "CPU 0/KVM", cpus="6")
    real_open = open

    def refuse(path, *args, **kwargs):
        if os.sep + "2000" + os.sep in str(path):
            raise OSError("no such process")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)

    assert pool._busy_by_threads(ISOLATED) == {4}


def test_qemu_scanner_skips_a_status_without_a_name(pool):
    d = os.path.join(pool._proc, "1000", "task", "1010")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Cpus_allowed_list:\t4\n")

    assert pool._busy_by_threads(ISOLATED) == set()


def test_qemu_scanner_skips_a_status_without_an_affinity(pool):
    d = os.path.join(pool._proc, "1000", "task", "1010")
    os.makedirs(d)
    with open(os.path.join(d, "status"), "w") as f:
        f.write("Name:\tCPU 0/KVM\n")

    assert pool._busy_by_threads(ISOLATED) == set()


def test_excluded_pids_are_not_counted_as_busy(pool):
    """Re-pinning a running VM must see its own cores as available."""
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")
    pool.exclude_pids({1000})

    assert pool._busy_by_threads(ISOLATED) == set()


def test_excluding_a_pid_also_excludes_its_vhost_threads(pool):
    # vhost threads live under their own PID; only their comm ties them back.
    write_status(pool._proc, 3000, 3000, "vhost-1000", cpus="5")
    pool.exclude_pids({1000})

    assert pool._busy_by_threads(ISOLATED) == set()


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
        write_stat(write_status(pool._proc, CLAIM_PID, 1010, "worker", cpus="4",
                                extra=f"Tgid:\t{CLAIM_PID}\nPPid:\t1\n"))

        assert pool.pinned_workload_threads() == {4: [1010]}


def test_workload_scanner_includes_the_children_of_a_run_process(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0, kind="run")
        write_stat(write_status(pool._proc, 2000, 2010, "worker", cpus="4",
                                extra=f"Tgid:\t2000\nPPid:\t{CLAIM_PID}\n"))

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

    assert pool.irq_cpus() == {6}


def test_irq_scanner_ignores_a_non_numeric_msi_entry(pool, tmp_path):
    make_sys_nic_irqs(tmp_path, [181], iface="eno1", sys_path=pool._sys)
    open(os.path.join(pool._sys, "class", "net", "eno1", "device",
                      "msi_irqs", "notanirq"), "w").close()
    make_proc_irq(tmp_path, {181: "6"}, proc_path=pool._proc)

    assert pool.irq_cpus() == {6}


def test_irq_scanner_skips_an_interrupt_with_no_affinity_file(pool, tmp_path):
    make_sys_nic_irqs(tmp_path, [181, 182], iface="eno1", sys_path=pool._sys)
    make_proc_irq(tmp_path, {181: "6"}, proc_path=pool._proc)

    assert pool.irq_cpus() == {6}


def test_an_interrupt_on_its_default_affinity_blocks_nothing(pool, tmp_path):
    # No nic-irq-affinity entry, no irqaffinity=, no irqbalance: the IRQ
    # keeps the all-CPUs mask, pinned to no isolated core in particular.
    make_sys_nic_irqs(tmp_path, [181], iface="eno1", sys_path=pool._sys)
    make_proc_irq(tmp_path, {181: "0-11"}, proc_path=pool._proc)

    assert pool.irq_cpus() == set()
    assert pool.free_logical() == sorted(ISOLATED)


def test_the_effective_affinity_wins_over_the_requested_one(pool, tmp_path):
    make_sys_nic_irqs(tmp_path, [181, 182], iface="eno1", sys_path=pool._sys)
    make_proc_irq(tmp_path, {181: "0-11", 182: "0-11"}, proc_path=pool._proc)
    for irq, cpu in ((181, "7"), (182, "1")):
        with open(os.path.join(pool._proc, "irq", str(irq),
                               "effective_affinity_list"), "w") as f:
            f.write(cpu + "\n")

    assert pool.irq_cpus() == {7}


def test_an_empty_effective_affinity_falls_back_on_the_requested_one(pool, tmp_path):
    make_sys_nic_irqs(tmp_path, [181], iface="eno1", sys_path=pool._sys)
    make_proc_irq(tmp_path, {181: "6"}, proc_path=pool._proc)
    with open(os.path.join(pool._proc, "irq", "181",
                           "effective_affinity_list"), "w") as f:
        f.write("\n")

    assert pool.irq_cpus() == {6}


def test_the_busy_set_is_memoized(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")

    first = pool.free_logical()
    # A second read must not rescan /proc: the pool is held under flock and
    # every caller inside that window sees one consistent picture.
    os.remove(os.path.join(pool._proc, "1000", "task", "1010", "status"))

    assert pool.free_logical() == first
    assert 4 not in pool.free_logical()


def test_busting_the_cache_forces_a_rescan(pool):
    write_status(pool._proc, 1000, 1010, "CPU 0/KVM", cpus="4")
    assert 4 not in pool.free_logical()

    os.remove(os.path.join(pool._proc, "1000", "task", "1010", "status"))
    pool.bust_cache()

    assert 4 in pool.free_logical()


def test_a_userspace_thread_pinned_outside_qemu_holds_its_core(pool):
    # A quadlet with CPUAffinity= or a taskset'd tool works today without
    # seapath-alloc: a dynamic VM must not land on its core.
    d = write_status(pool._proc, 1000, 1010, "sv-subscriber", cpus="4")
    write_stat(d)

    assert pool._busy_by_threads(ISOLATED) == {4}
    assert 4 not in pool.free_logical()


def test_a_kernel_thread_bound_to_an_isolated_core_is_not_busy(pool):
    # ksoftirqd/N, kworker/N:x and friends sit on every core by design.
    d = write_status(pool._proc, 30, 30, "ksoftirqd/4", cpus="4")
    write_stat(d, flags=KTHREAD)

    assert pool._busy_by_threads(ISOLATED) == set()


def test_a_vhost_kernel_thread_holds_its_core(pool):
    # Before Linux 6.4 vhost workers are kernel threads, still VM workload.
    d = write_status(pool._proc, 3000, 3000, "vhost-1000", cpus="5")
    write_stat(d, flags=KTHREAD)

    assert pool._busy_by_threads(ISOLATED) == {5}


def test_a_thread_whose_stat_cannot_be_read_is_skipped(pool):
    write_status(pool._proc, 1000, 1010, "sshd", cpus="4")

    assert pool._busy_by_threads(ISOLATED) == set()


def test_a_malformed_stat_is_skipped(pool):
    d = write_status(pool._proc, 1000, 1010, "sshd", cpus="4")
    with open(os.path.join(d, "stat"), "w") as f:
        f.write("1010 (sshd) S 1\n")

    assert pool._busy_by_threads(ISOLATED) == set()


def test_a_qemu_tool_holds_its_core_and_stays_put(pool):
    # qemu-img or qemu-nbd pinned by someone holds its core; the repacker
    # only moves VM threads and leaves it where it is.
    d = write_status(pool._proc, 1000, 1010, "qemu-img", cpus="4")
    write_stat(d)

    assert pool._busy_by_threads(ISOLATED) == {4}
    assert pool.pinned_workload_threads() == {}


def test_the_qemu_kvm_binary_is_a_workload(pool):
    write_status(pool._proc, 1000, 1000, "qemu-kvm", cpus="4")

    assert pool.pinned_workload_threads() == {4: [1000]}


def test_a_qemu_iothread_is_a_workload_unlike_the_monitor_one(pool):
    write_status(pool._proc, 1000, 1030, "IO iothread1", cpus="4")
    d = write_status(pool._proc, 1000, 1031, "IO mon_iothread", cpus="6")
    write_stat(d)

    assert pool.pinned_workload_threads() == {4: [1030]}


def test_quadlet_claims_are_reported_with_their_service(pool):
    with pool:
        pool.add_claim("redis", CLAIM_PID, [4], "OTHER", 0, kind="quadlet")

        assert pool.pinned_quadlet_cpus() == {4: ("redis", "redis.service")}


def test_a_non_quadlet_claim_is_not_a_cgroup_move_candidate(pool):
    with pool:
        pool.add_claim("sv", CLAIM_PID, [4], "OTHER", 0, kind="run")

        assert pool.pinned_quadlet_cpus() == {}


def test_a_quadlet_spanning_several_cores_is_not_a_candidate(pool):
    # The repacker moves one core at a time; a multi-core container is not
    # something it can relocate.
    with pool:
        pool.add_claim("redis", CLAIM_PID, [4, 6], "OTHER", 0, kind="quadlet")

        assert pool.pinned_quadlet_cpus() == {}


def test_a_claim_on_a_housekeeping_core_holds_no_isolated_core(pool):
    with pool:
        pool.add_claim("hk", CLAIM_PID, [1, 4], "OTHER", 0)

        assert pool._busy_by_claims(ISOLATED) == {4}


@pytest.mark.parametrize("name", ["claims.json", ".reserved_siblings"])
def test_a_state_file_that_is_not_a_list_reads_as_empty(pool, name):
    os.makedirs(pool._alloc_dir)
    with open(os.path.join(pool._alloc_dir, name), "w") as f:
        f.write('{"not": "a list"}')

    assert pool._load_claims() == []
    assert pool._load_reserved_siblings() == []
