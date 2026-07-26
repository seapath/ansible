# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import os
import pytest
from seapath_alloc.pool import CorePool
from seapath_alloc.topology import Topology
from tests.conftest import (make_cpu_topology, make_proc_qemu, make_proc_irq,
                            make_sys_nic_irqs)


@pytest.fixture
def pool_env(tmp_path, std_topology):
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    proc_path = str(tmp_path / "proc")
    os.makedirs(proc_path)
    return std_topology, alloc_dir, proc_path


def make_pool(topology, alloc_dir, proc_path, sys_path=None):
    # Default to a path with no NIC MSI entries so tests don't pick up
    # real system IRQs from the machine running the suite.
    pool = CorePool(
        topology=topology, alloc_dir=alloc_dir, proc_path=proc_path,
        sys_path=sys_path or "/nonexistent-sys-for-tests",
    )
    pool.lock()
    return pool


# ------------------------------------------------------------------ free_logical

def test_empty_proc_all_isolated_free(pool_env):
    topo, alloc_dir, proc_path = pool_env
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        free = pool.free_logical()
    finally:
        pool.unlock()
    assert free == [4, 5, 6, 7, 8, 9, 10, 11]


def test_pinned_qemu_thread_reduces_free(tmp_path, sys_path):
    topo = Topology(sys_cpu_path=sys_path)
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="vm1",
                                vcpu_count=1, vcpu_cpus=[4])
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        free = pool.free_logical()
    finally:
        pool.unlock()
    assert 4 not in free
    assert 5 in free


def test_unpinned_qemu_thread_not_counted(tmp_path, sys_path):
    """A thread with all CPUs in its mask is not counted as holding isolated cores."""
    topo = Topology(sys_cpu_path=sys_path)
    # vcpu_cpus=None → default "0-11" (unpinned)
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="vm1", vcpu_count=1)
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        free = pool.free_logical()
    finally:
        pool.unlock()
    assert free == [4, 5, 6, 7, 8, 9, 10, 11]


def test_irq_on_isolated_reduces_free(tmp_path, sys_path):
    topo = Topology(sys_cpu_path=sys_path)
    proc_path = str(tmp_path / "proc")
    os.makedirs(proc_path)
    # IRQs 10 and 11 pinned to isolated CPUs 6 and 7
    make_proc_irq(tmp_path, {10: "6", 11: "7"}, proc_path=proc_path)
    # Declare IRQs 10 and 11 as NIC MSI IRQs so the pool counts them
    fake_sys = make_sys_nic_irqs(tmp_path, [10, 11])
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    pool = make_pool(topo, alloc_dir, proc_path, sys_path=fake_sys)
    try:
        free = pool.free_logical()
    finally:
        pool.unlock()
    assert 6 not in free
    assert 7 not in free
    assert 4 in free


# ------------------------------------------------------------------ free_physical

def test_free_physical_returns_lower_siblings(pool_env):
    topo, alloc_dir, proc_path = pool_env
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        free_p = pool.free_physical()
    finally:
        pool.unlock()
    assert free_p == [4, 6, 8, 10]  # lower siblings of (4,5),(6,7),(8,9),(10,11)


def test_reserved_sibling_blocks_physical(tmp_path, sys_path):
    topo = Topology(sys_cpu_path=sys_path)
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="vm1",
                                vcpu_count=1, vcpu_cpus=[4])
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        pool.add_reserved_sibling(idle_cpu=5, active_cpu=4)
        free_p = pool.free_physical()
    finally:
        pool.unlock()
    # Pair (4,5) is fully occupied: 4 by vcpu, 5 reserved
    assert 4 not in free_p
    assert 6 in free_p


def test_stale_reserved_sibling_released(tmp_path, sys_path):
    """When the active CPU is no longer pinned (VM died), the reservation lapses."""
    topo = Topology(sys_cpu_path=sys_path)
    # No QEMU process — active_cpu=4 won't appear in any affinity
    proc_path = str(tmp_path / "proc")
    os.makedirs(proc_path)
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    # Manually write a stale reserved sibling
    import json
    with open(os.path.join(alloc_dir, ".reserved_siblings"), 'w') as f:
        json.dump([[5, 4]], f)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        free_p = pool.free_physical()
    finally:
        pool.unlock()
    # Stale entry gone — pair (4,5) is free again
    assert 4 in free_p


# ------------------------------------------------------------------ claims

def test_claim_reduces_free(pool_env):
    topo, alloc_dir, proc_path = pool_env
    import os as _os
    fake_pid = _os.getpid()
    # The pool checks pid liveness via proc_path; create a fake entry so
    # the claim is not immediately expired.
    os.makedirs(os.path.join(proc_path, str(fake_pid)), exist_ok=True)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        pool.add_claim("test", fake_pid, [8, 9])
        free = pool.free_logical()
    finally:
        pool.unlock()
    assert 8 not in free
    assert 9 not in free


# ------------------------------------------------------------------ exclude_pids

def test_exclude_pids_frees_logical_cpu(tmp_path, sys_path):
    """Excluding the QEMU PID makes its pinned logical CPU available."""
    topo = Topology(sys_cpu_path=sys_path)
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="vm1",
                                vcpu_count=1, vcpu_cpus=[4])
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        assert 4 not in pool.free_logical()
        pool.exclude_pids({1000})
        assert 4 in pool.free_logical()
    finally:
        pool.unlock()


def test_exclude_pids_frees_reserved_sibling(tmp_path, sys_path):
    """Excluding a PID whose active_cpu is reserved also frees the idle sibling."""
    topo = Topology(sys_cpu_path=sys_path)
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="vm1",
                                vcpu_count=1, vcpu_cpus=[4])
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        pool.add_reserved_sibling(idle_cpu=5, active_cpu=4)
        # Pair (4,5) is fully occupied: cpu4 by the thread, cpu5 reserved.
        assert 4 not in pool.free_physical()

        pool.exclude_pids({1000})
        # Thread on cpu4 is excluded → active_cpu=4 no longer "pinned" →
        # reservation lapses → pair (4,5) becomes free.
        assert 4 in pool.free_physical()
    finally:
        pool.unlock()


def test_exclude_pids_covers_vhost_kthreads(tmp_path, sys_path):
    """
    vhost kernel threads live under their own PID, not the QEMU PID; only
    their comm ("vhost-<qemu_pid>") ties them to the VM. Excluding the QEMU
    PID must also exclude them, or a re-pin of a running VM would still see
    its own vhost cores as busy.
    """
    topo = Topology(sys_cpu_path=sys_path)
    proc_path = make_proc_qemu(tmp_path, pid=1000, vm_name="vm1",
                                vcpu_count=1, vcpu_cpus=[4])
    vhost_task = tmp_path / "proc" / "3000" / "task" / "3000"
    vhost_task.mkdir(parents=True)
    (vhost_task / "status").write_text(
        "Name:\tvhost-1000\nPid:\t3000\nCpus_allowed_list:\t7\n"
    )
    alloc_dir = str(tmp_path / "alloc")
    os.makedirs(alloc_dir)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        assert 7 not in pool.free_logical()
        pool.exclude_pids({1000})
        assert 7 in pool.free_logical()
    finally:
        pool.unlock()


def test_expired_claim_auto_removed(pool_env):
    topo, alloc_dir, proc_path = pool_env
    import json
    # Write a claim with a bogus PID that doesn't exist
    with open(os.path.join(alloc_dir, "claims.json"), 'w') as f:
        json.dump([{"label": "dead", "pid": 999999999, "cores": [8]}], f)
    pool = make_pool(topo, alloc_dir, proc_path)
    try:
        free = pool.free_logical()
        claims = pool.all_claims()
    finally:
        pool.unlock()
    assert 8 in free
    assert claims == []
