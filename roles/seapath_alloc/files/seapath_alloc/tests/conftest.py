# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Shared pytest fixtures.

Topology used throughout:
  online:     0-11
  isolated:   4-11
  housekeeping: 0-3
  HT pairs:   (0,1), (2,3), (4,5), (6,7), (8,9), (10,11)
"""

import os
import pytest


def make_cpu_topology(tmp_path,
                      online="0-11",
                      isolated="4-11",
                      pairs=None):
    """
    Build a fake /sys/devices/system/cpu tree under tmp_path.

    pairs: list of (lo, hi) tuples; defaults to 2-way HT for online range.
    """
    if pairs is None:
        pairs = [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11)]

    cpu_path = tmp_path / "sys" / "devices" / "system" / "cpu"
    cpu_path.mkdir(parents=True)
    (cpu_path / "online").write_text(online + "\n")
    (cpu_path / "isolated").write_text(isolated + "\n")

    # Build a sibling_list for each CPU
    sibling_map = {}
    for lo, hi in pairs:
        for c in range(lo, hi + 1):
            members = list(range(lo, hi + 1))
            sibling_map[c] = ",".join(str(m) for m in members)

    from seapath_alloc.topology import parse_cpu_list
    for cpu in parse_cpu_list(online):
        topo_dir = cpu_path / f"cpu{cpu}" / "topology"
        topo_dir.mkdir(parents=True)
        siblings = sibling_map.get(cpu, str(cpu))
        (topo_dir / "thread_siblings_list").write_text(siblings + "\n")

    return str(cpu_path)


def make_proc_qemu(tmp_path, pid: int, vm_name: str, vcpu_count: int,
                   vhost_count: int = 0, iothread_count: int = 0,
                   vcpu_cpus: list = None, emulator_cpu: int = None,
                   vhost_cpus: list = None):
    """
    Build a fake /proc/<pid>/ tree for a QEMU process.

    vcpu_cpus: per-vCPU Cpus_allowed_list; defaults to all-online (unpinned).
    emulator_cpu: single CPU for emulator; defaults to unpinned.
    vhost_cpus: per-vhost Cpus_allowed_list; defaults to unpinned.
    """
    all_cpus = "0-11"

    proc = tmp_path / "proc"
    pid_dir = proc / str(pid)

    # cmdline
    cmdline_args = [
        "/usr/bin/qemu-system-x86_64",
        f"-name guest={vm_name},debug-threads=on",
        "-m", "2048",
    ]
    (pid_dir).mkdir(parents=True)
    (pid_dir / "cmdline").write_bytes(b"\x00".join(
        a.encode() for a in cmdline_args
    ) + b"\x00")

    task_dir = pid_dir / "task"

    def make_tid(tid, comm, cpus_allowed):
        d = task_dir / str(tid)
        d.mkdir(parents=True)
        (d / "comm").write_text(comm + "\n")
        status = (
            f"Name:\t{comm}\n"
            f"Pid:\t{tid}\n"
            f"Cpus_allowed_list:\t{cpus_allowed}\n"
        )
        (d / "status").write_text(status)

    # emulator (TID == PID)
    emu_cpu = str(emulator_cpu) if emulator_cpu is not None else all_cpus
    make_tid(pid, "qemu-system-x86_64", emu_cpu)

    # vCPUs
    for i in range(vcpu_count):
        tid = pid + 10 + i
        cpu = str(vcpu_cpus[i]) if vcpu_cpus and i < len(vcpu_cpus) else all_cpus
        make_tid(tid, f"CPU {i}/KVM", cpu)

    # vhost
    for i in range(vhost_count):
        tid = pid + 20 + i
        cpu = str(vhost_cpus[i]) if vhost_cpus and i < len(vhost_cpus) else all_cpus
        make_tid(tid, f"vhost-{pid}", cpu)

    # iothread
    for i in range(iothread_count):
        tid = pid + 30 + i
        make_tid(tid, f"iothread{i}", all_cpus)

    return str(proc)


def make_proc_irq(tmp_path, irq_map: dict, proc_path: str = None):
    """
    Add /proc/irq/<N>/smp_affinity_list files.

    irq_map: {irq_number: cpu_list_string}, e.g. {10: "6", 11: "7"}
    proc_path: reuse an existing fake /proc if provided.
    """
    if proc_path is None:
        proc_path = str(tmp_path / "proc")
    for irq_num, cpu_list in irq_map.items():
        irq_dir = os.path.join(proc_path, "irq", str(irq_num))
        os.makedirs(irq_dir, exist_ok=True)
        with open(os.path.join(irq_dir, "smp_affinity_list"), 'w') as f:
            f.write(cpu_list + "\n")
    return proc_path


def make_sys_nic_irqs(tmp_path, irq_nums: list,
                      iface: str = "eth0", sys_path: str = None):
    """
    Create fake /sys/class/net/<iface>/device/msi_irqs/<N> entries.

    Mirrors what the kernel exposes for physical NICs with MSI-X interrupts.
    sys_path: sysfs root; defaults to tmp_path/sys (consistent with
              make_cpu_topology which writes under tmp_path/sys/devices/…).
    """
    if sys_path is None:
        sys_path = str(tmp_path / "sys")
    msi_dir = os.path.join(sys_path, "class", "net", iface, "device", "msi_irqs")
    os.makedirs(msi_dir, exist_ok=True)
    for irq_num in irq_nums:
        open(os.path.join(msi_dir, str(irq_num)), 'w').close()
    return sys_path


@pytest.fixture
def sys_path(tmp_path):
    """Standard 12-core topology: 0-3 housekeeping, 4-11 isolated, 2-way HT."""
    return make_cpu_topology(tmp_path)


@pytest.fixture
def std_topology(sys_path):
    from seapath_alloc.topology import Topology
    return Topology(sys_cpu_path=sys_path)
