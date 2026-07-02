# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Live data collection for the seapath-alloc pool.

Functions here read /proc, /sys, and the pool state to produce structured
data about current CPU allocation.  They have no side effects and can be
called without holding any lock beyond the pool flock inside collect().

The CLI entry point (seapath-alloc) is in cli.py; the Prometheus exporter
imports collect() directly.
"""

import glob
import os
import re

from .pool import CorePool, _is_qemu_comm
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
        path = os.path.join(proc_path, "irq", str(irq_num), "smp_affinity_list")
        try:
            with open(path) as f:
                content = f.read().strip()
        except OSError:
            continue
        cpus = frozenset(parse_cpu_list(content)) & isolated
        if cpus:
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


def _slot_warnings(members: list) -> list:
    """
    Risky-but-allowed colocation patterns, as stable reason identifiers.

    equal_rt_priority — two distinct actors with the same FIFO/RR priority
      share the slot: neither ever preempts the other, so whichever runs
      first can starve the other indefinitely.
    rt_priority_ge_irq — a FIFO/RR member at priority >= 50 shares the slot
      with NIC IRQs, whose irq threads run at the kernel default FIFO/50:
      a CPU-hungry member can starve interrupt handling.
    vcpu_shared — a vCPU shares the slot with other actors: preempting a
      vCPU while the guest kernel holds a spinlock can cause guest-visible
      stalls (RCU, soft lockups).
    """
    warnings = []
    rt = [m for m in members if m.get("scheduler") in ("FIFO", "RR")]

    prio_actors: dict = {}
    for m in rt:
        prio_actors.setdefault(m.get("priority", 0), set()).add(
            (m["label"], m["group"]))
    if any(len(actors) > 1 for actors in prio_actors.values()):
        warnings.append("equal_rt_priority")

    has_irq = any(m["kind"] == "irq" for m in members)
    if has_irq and any(m.get("priority", 0) >= 50 for m in rt):
        warnings.append("rt_priority_ge_irq")

    has_vcpu = any(m["kind"] == "vm" and m["group"].startswith("CPU ")
                   for m in members)
    if has_vcpu and len(members) > 1:
        warnings.append("vcpu_shared")

    return warnings


def _build_slots(slots: list, actors: list) -> list:
    """
    Attach members to each active slot by intersecting the slot's cores with
    the actors' pinned CPUs. Membership is purely observational — derived
    from the same live data as the actor list, never stored.
    """
    result = []
    for slot in slots:
        cores = set(slot.get("cores", []))
        members = []
        for actor in actors:
            if actor["type"] == "vm":
                for th in actor.get("threads", []):
                    if set(parse_cpu_list(th["cpus"])) & cores:
                        members.append({
                            "kind": "vm",
                            "label": actor["label"],
                            "group": th["comm"],
                            "scheduler": th.get("scheduler", ""),
                            "priority": th.get("priority", 0),
                            "cpus": th["cpus"],
                        })
            elif set(parse_cpu_list(actor.get("cpus", ""))) & cores:
                members.append({
                    "kind": actor["type"],
                    "label": actor["label"],
                    "group": actor["type"],
                    "scheduler": actor.get("scheduler", ""),
                    "priority": actor.get("priority", 0),
                    "cpus": actor.get("cpus", ""),
                })
        result.append({
            "name": slot["name"],
            "cores": format_cpu_list(sorted(cores)),
            "isolation": slot.get("isolation", ""),
            "members": members,
            "warnings": _slot_warnings(members),
        })
    return result


def collect(proc_path: str = "/proc", sys_path: str = "/sys") -> dict:
    topo = Topology()
    isolated = set(topo.isolated_cpus())

    with CorePool(topology=topo, proc_path=proc_path, sys_path=sys_path) as pool:
        free_l = pool.free_logical()
        free_p = pool.free_physical()
        claims = pool.all_claims()
        reserved = pool.active_reserved_siblings()
        slots = pool.slots()

    vm_actors = _read_qemu_actors(proc_path, isolated)
    irq_actors = _read_irq_actors(proc_path, isolated, sys_path=sys_path)
    claim_actors = [
        {
            "type": c.get("kind") or "claim",
            "label": c["label"],
            "pid": c.get("pid"),
            "cpus": format_cpu_list(c.get("cores", [])),
            "scheduler": c.get("scheduler", ""),
            "priority": c.get("priority", 0),
            "slot": c.get("slot", ""),
        }
        for c in claims
    ]
    actors = vm_actors + irq_actors + claim_actors

    return {
        "isolated": format_cpu_list(sorted(isolated)),
        "free_logical": format_cpu_list(free_l),
        "free_physical": format_cpu_list(free_p),
        "actors": actors,
        "reserved_siblings": reserved,
        "slots": _build_slots(slots, actors),
    }
