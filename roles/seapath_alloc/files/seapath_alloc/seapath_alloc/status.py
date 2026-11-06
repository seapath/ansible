# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Live data collection for the seapath-alloc pool.

Functions here read /proc, /sys, and the pool state to produce structured
data about current CPU allocation.  They change nothing but the expired
claims, which reading the pool prunes from claims.json under the pool flock
that collect() takes.

The CLI entry point (seapath-alloc) is in cli.py; the Prometheus exporter
imports collect() directly.
"""

import glob
import os
import re

from .pool import _PF_KTHREAD, CorePool, _is_qemu_comm, _read_stat
from .topology import Topology, parse_cpu_list, format_cpu_list


_POLICY_NAME = {0: "OTHER", 1: "FIFO", 2: "RR", 3: "BATCH", 5: "IDLE", 6: "DEADLINE"}


def _read_sched(stat_path: str):
    """
    Return (policy_name, rt_priority) from /proc/.../stat.

    Fields after the comm token (enclosed in parens):
      index 37 = rt_priority (0 for non-RT, 1-99 for FIFO/RR)
      index 38 = policy integer (see _POLICY_NAME)
    """
    try:
        with open(stat_path) as f:
            data = f.read()
        after_comm = data[data.rfind(')') + 2:]
        fields = after_comm.split()
        policy_name = _POLICY_NAME.get(int(fields[38]), "?")
        rt_prio = int(fields[37])
        return policy_name, rt_prio
    except (OSError, IndexError, ValueError):
        return "", 0


def _read_qemu_actors(proc_path: str, isolated: set) -> list:
    """Group QEMU threads by VM and return a list of actor dicts."""
    vms = {}
    pattern = os.path.join(proc_path, "*/task/*/status")
    for status_path in glob.glob(pattern):
        try:
            with open(status_path) as f:
                content = f.read()
        except OSError:
            continue
        name_m = re.search(r'^Name:\s+(.+)', content, re.M)
        if not name_m:
            continue
        comm = name_m.group(1).strip()

        if not _is_qemu_comm(comm):
            continue

        allowed_m = re.search(r'^Cpus_allowed_list:\s+(\S+)', content, re.M)
        if not allowed_m:
            continue
        allowed = set(parse_cpu_list(allowed_m.group(1)))
        if not allowed.issubset(isolated):
            continue

        # Extract VM name from the process cmdline.
        # status_path = /proc/<pid>/task/<tid>/status → pid is at index -4.
        pid = status_path.split(os.sep)[-4]
        tid = status_path.split(os.sep)[-2]

        # vhost threads are kernel threads (their /proc/<tid>/cmdline is
        # empty). Their comm encodes the QEMU PID as "vhost-<qemu_pid>",
        # so use that PID to look up the QEMU cmdline instead.
        m_vhost = re.match(r'vhost-(\d+)$', comm)
        qemu_pid = m_vhost.group(1) if m_vhost else pid

        vm_name = ""
        try:
            cmdline_path = os.path.join(proc_path, qemu_pid, "cmdline")
            with open(cmdline_path, 'rb') as f:
                raw = f.read().decode('utf-8', errors='replace')
            # /proc/cmdline separates arguments with \x00, not spaces.
            m = re.search(r'-name[\x00 ]guest=([^,\x00 ]+)', raw)
            if m:
                vm_name = m.group(1)
        except OSError:
            pass

        stat_path = os.path.join(proc_path, pid, "task", tid, "stat")
        policy, rt_prio = _read_sched(stat_path)

        key = vm_name or f"pid-{qemu_pid}"
        if key not in vms:
            vms[key] = {"type": "vm", "label": key, "threads": []}
        vms[key]["threads"].append({
            "comm": comm,
            "cpus": format_cpu_list(sorted(allowed)),
            "scheduler": policy,
            "priority": rt_prio,
        })

    return list(vms.values())


def _read_pinned_actors(proc_path: str, isolated: set, covered: set) -> list:
    """
    Processes pinned to isolated cores outside seapath-alloc: a quadlet with
    CPUAffinity=, a tool started with taskset. The pool counts their cores
    as busy; this names who holds them.

    Userspace threads only (kernel threads are bound to every core by
    design), QEMU threads excepted (they are VM actors), and so are threads
    whose cores belong to a claim (or later a slot), which already name
    them.
    Grouped by process.
    """
    procs: dict = {}
    for status_path in glob.glob(os.path.join(proc_path, "*/task/*/status")):
        try:
            with open(status_path) as f:
                content = f.read()
        except OSError:
            continue
        name_m = re.search(r'^Name:\s+(.+)', content, re.M)
        allowed_m = re.search(r'^Cpus_allowed_list:\s+(\S+)', content, re.M)
        if not name_m or not allowed_m:
            continue
        allowed = set(parse_cpu_list(allowed_m.group(1)))
        if not allowed or not allowed <= isolated or allowed <= covered:
            continue
        if _is_qemu_comm(name_m.group(1).strip()):
            continue
        task_dir = os.path.dirname(status_path)
        stat = _read_stat(os.path.join(task_dir, "stat"))
        if stat is None or stat[0] & _PF_KTHREAD:
            continue
        pid = status_path.split(os.sep)[-4]
        entry = procs.setdefault(pid, {"cpus": set(), "tasks": []})
        entry["cpus"] |= allowed
        entry["tasks"].append(task_dir)

    actors = []
    for pid in sorted(procs, key=int):
        try:
            with open(os.path.join(proc_path, pid, "comm")) as f:
                comm = f.read().strip()
        except OSError:
            comm = ""
        # The main thread's policy, whichever thread the glob met first.
        main = os.path.join(proc_path, pid, "task", pid)
        task = main if main in procs[pid]["tasks"] else procs[pid]["tasks"][0]
        policy, rt_prio = _read_sched(os.path.join(task, "stat"))
        actors.append({
            "type": "pinned",
            "label": f"{comm}[{pid}]",
            "pid": int(pid),
            "cpus": format_cpu_list(sorted(procs[pid]["cpus"])),
            "scheduler": policy,
            "priority": rt_prio,
        })
    return actors


def _read_irq_actors(proc_path: str, isolated: set,
                     sys_path: str = "/sys") -> list:
    """
    Return NIC MSI IRQ actors on isolated cores, grouped by interface.

    Reads NIC IRQ numbers from /sys/class/net/*/device/msi_irqs/ so that only
    user-relevant NIC IRQs appear — kernel-managed MSI IRQs (storage, USB, …)
    assigned by isolcpus=managed_irq are excluded.

    IRQs belonging to the same interface and pinned to the same CPU set are
    collapsed into one entry (label = "<iface>/<irq-range>", e.g. "eno1/181-189").
    Multi-queue NICs with queues spread across different CPUs produce one entry
    per CPU group.
    """
    # iface → [(irq_num, frozenset(cpus))]
    iface_irqs: dict = {}
    for entry in glob.glob(
            os.path.join(sys_path, "class/net/*/device/msi_irqs/*")):
        try:
            irq_num = int(os.path.basename(entry))
        except ValueError:
            continue
        # entry: .../class/net/<iface>/device/msi_irqs/<N>
        iface = entry.split(os.sep)[-4]
        # Same rule as the pool: the effective affinity when the kernel
        # exposes it, and only an IRQ routed to isolated cores alone.
        cpus = frozenset()
        for name in ("effective_affinity_list", "smp_affinity_list"):
            path = os.path.join(proc_path, "irq", str(irq_num), name)
            try:
                with open(path) as f:
                    cpus = frozenset(parse_cpu_list(f.read()))
            except OSError:
                continue
            if cpus:
                break
        if cpus and cpus <= isolated:
            iface_irqs.setdefault(iface, []).append((irq_num, cpus))

    actors = []
    for iface in sorted(iface_irqs):
        # Group IRQ numbers by their CPU affinity set
        cpu_groups: dict = {}  # frozenset(cpus) → [irq_num, ...]
        for irq_num, cpus in iface_irqs[iface]:
            cpu_groups.setdefault(cpus, []).append(irq_num)
        for cpus, irq_nums in sorted(cpu_groups.items(), key=lambda x: min(x[1])):
            irq_range = format_cpu_list(sorted(irq_nums))
            actors.append({
                "type": "irq",
                "label": f"{iface}/{irq_range}",
                "iface": iface,
                "irqs": irq_range,
                "cpus": format_cpu_list(sorted(cpus)),
            })
    return actors


def collect(proc_path: str = "/proc", sys_path: str = "/sys") -> dict:
    topo = Topology(os.path.join(sys_path, "devices", "system", "cpu"))
    isolated = set(topo.isolated_cpus())

    with CorePool(topology=topo, proc_path=proc_path, sys_path=sys_path) as pool:
        free_l = pool.free_logical()
        free_p = pool.free_physical()
        claims = pool.all_claims()

    vm_actors = _read_qemu_actors(proc_path, isolated)
    irq_actors = _read_irq_actors(proc_path, isolated, sys_path=sys_path)
    claim_actors = [
        {"type": "claim", "label": c["label"], "pid": c.get("pid"),
         "cpus": format_cpu_list(c.get("cores", [])),
         "scheduler": c.get("scheduler", ""), "priority": c.get("priority", 0)}
        for c in claims
    ]
    covered = set()
    for c in claims:
        covered.update(c.get("cores", []))
    pinned_actors = _read_pinned_actors(proc_path, isolated, covered)

    return {
        "isolated": format_cpu_list(sorted(isolated)),
        "free_logical": format_cpu_list(free_l),
        "free_physical": format_cpu_list(free_p),
        "actors": vm_actors + irq_actors + claim_actors + pinned_actors,
    }
