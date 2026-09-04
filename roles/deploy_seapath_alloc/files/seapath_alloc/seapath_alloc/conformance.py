# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Host real-time tuning, read for the Prometheus textfile.

The rest of seapath-alloc answers what the isolated cores are *doing*. This
module answers the other half of the same question: what the machine was
*tuned as*. The tuned profile, the boot parameters, the RT throttling
sysctls, the hugepage pools, SMT, transparent hugepages, the interrupt
affinities and ACPI are all ordinary files on the host, and none of them is
published by prometheus-node-exporter.

They are read here because this collector already runs on the host, on a
timer, and already writes a textfile node_exporter serves. A management
interface that wants them for a whole cluster then makes one HTTP GET per
node, instead of opening an SSH connection on every page refresh.

Everything here is a reading, never a verdict. Whether a value is right for a
given machine depends on what that machine's inventory declares, which this
collector does not have and must not guess: it reports what it read, and the
consumer holding the inventory decides what that means.

An unreadable value is reported as absent (None, or an empty string) rather
than as a default. The difference matters to the consumer: a machine with no
tuned profile selected and a machine whose /etc could not be read are two
different faults, fixed by two different actions.

proc_path, sys_path and etc_path let unit tests inject a recorded tree, the
same way Topology takes sys_cpu_path.
"""

import os
import re

from .topology import parse_cpu_list

# How many offending interrupts are described one by one. The count beside
# them is always the true one: a machine that keeps nothing off its isolated
# cores has every interrupt on the list, and one series per interrupt, per
# node, forever, is a cardinality bill nobody agreed to pay for a finding the
# count already carries.
IRQ_DETAIL_LIMIT = 8


def _read(*parts) -> str:
    """The stripped content of a file, or "" when it cannot be read.

    Absent and unreadable are the same answer here: both mean this collector
    has nothing to say about the value, which is what an empty string means to
    every caller below.
    """
    try:
        with open(os.path.join(*parts)) as f:
            return f.read().strip()
    except OSError:
        return ""


def _read_int(*parts):
    raw = _read(*parts)
    try:
        return int(raw)
    except ValueError:
        return None


def _bracketed(raw: str) -> str:
    """The selected choice of a sysfs multiple-choice file.

    "always madvise [never]" is how the kernel writes an enumeration: every
    value it accepts, with the active one in brackets.
    """
    match = re.search(r"\[([^\]]+)\]", raw)
    return match.group(1) if match else ""


def tuned_profile(etc_path: str = "/etc", usr_path: str = "/usr") -> dict:
    """The profile this machine is configured with, and whether it exists.

    /etc/tuned/active_profile is what an Ansible run writes and what survives
    a reboot. The daemon's own /run/tuned/active_profile is deliberately not
    read: the configured profile is the one an inventory can be held against,
    and the running one is live state.

    A machine naming a profile that is installed nowhere is a machine tuned by
    nothing, and `tuned-adm active` reports the name either way, so the
    directory is looked for rather than trusted.
    """
    profile = _read(etc_path, "tuned", "active_profile")
    if not profile:
        return {"profile": "", "source": "", "installed": None}

    # Ansible drops site profiles under profiles/, older layouts put them
    # directly under /etc/tuned, and the distribution ships its own.
    candidates = [
        os.path.join(etc_path, "tuned", "profiles", profile),
        os.path.join(etc_path, "tuned", profile),
        os.path.join(usr_path, "lib", "tuned", profile),
        os.path.join(usr_path, "lib", "tuned", "profiles", profile),
    ]
    return {
        "profile": profile,
        "source": os.path.join(etc_path, "tuned", "active_profile"),
        "installed": any(os.path.isdir(path) for path in candidates),
    }


def kernel_cmdline(proc_path: str = "/proc") -> str:
    """The command line this kernel booted with, verbatim.

    Verbatim because the parameters that matter to latency are not a fixed
    list: nohz_full and rcu_nocbs are today's question, a C-state limit is
    written by the tuned profile's [bootloader] section, and the next one will
    be something else. Publishing the string leaves the reading here and the
    opinion with whoever holds the inventory.

    It is also the only place isolcpus= can be seen once the kernel has
    consumed it: /sys/devices/system/cpu/isolated shows the result, not the
    request, and the two differ on a machine converged and never rebooted.
    """
    return _read(proc_path, "cmdline")


def sched_rt(proc_path: str = "/proc") -> dict:
    """The real-time throttling window.

    A runtime of -1 disables throttling entirely, which is what the realtime
    tuned profile sets and a legitimate value. So an unreadable sysctl is
    reported as None and never as -1.
    """
    return {
        "runtime_us": _read_int(proc_path, "sys/kernel/sched_rt_runtime_us"),
        "period_us": _read_int(proc_path, "sys/kernel/sched_rt_period_us"),
    }


def hugepages(sys_path: str = "/sys") -> list:
    """Every hugepage pool, machine-wide and per NUMA node.

    Both, because they answer different questions. A guest pinned to one
    socket draws its pages from that socket's pool, so a machine with enough
    pages in total and none on the node the guest sits on fails to start with
    the total looking correct.

    node is None for the machine-wide pools and the NUMA node number for the
    others.
    """
    roots = [(os.path.join(sys_path, "kernel/mm/hugepages"), None)]
    node_root = os.path.join(sys_path, "devices/system/node")
    for entry in sorted(_listdir(node_root)):
        match = re.fullmatch(r"node(\d+)", entry)
        if match:
            roots.append(
                (os.path.join(node_root, entry, "hugepages"), int(match.group(1)))
            )

    pools = []
    for root, node in roots:
        for entry in sorted(_listdir(root)):
            match = re.fullmatch(r"hugepages-(\d+)kB", entry)
            if not match:
                continue
            total = _read_int(root, entry, "nr_hugepages")
            if total is None:
                continue
            free = _read_int(root, entry, "free_hugepages")
            pools.append({
                "size_kb": int(match.group(1)),
                "node": node,
                "total": total,
                "free": free if free is not None else 0,
            })
    return pools


def transparent_hugepages(sys_path: str = "/sys") -> dict:
    """khugepaged's two controls, which compact memory in the background."""
    root = os.path.join(sys_path, "kernel/mm/transparent_hugepage")
    return {
        "enabled": _bracketed(_read(root, "enabled")),
        "defrag": _bracketed(_read(root, "defrag")),
    }


def smt(sys_path: str = "/sys") -> dict:
    """Whether two threads share a physical core's execution units.

    active is None on the machines that expose no SMT control at all, which is
    usual on AMD and on a machine whose firmware disabled it. That is a
    different answer from "off" and is kept apart from it.
    """
    root = os.path.join(sys_path, "devices/system/cpu/smt")
    active = _read_int(root, "active")
    return {
        "active": None if active is None else bool(active),
        "control": _read(root, "control"),
    }


def acpi_present(sys_path: str = "/sys") -> bool:
    """Whether the firmware exposes ACPI, which is where SMIs come from.

    Nothing here measures an SMI: they are invisible to the kernel by
    construction, and hwlatdetect is what measures them. This says only
    whether the machine has the firmware layer that issues them.
    """
    return os.path.isdir(os.path.join(sys_path, "firmware/acpi"))


def irq_affinity(isolated, proc_path: str = "/proc") -> dict:
    """Which interrupts are still allowed to land on an isolated CPU.

    An affinity mask is a permission rather than an observation: an interrupt
    allowed on an isolated core is a latency source whether or not it has
    fired there yet, which is a property of the machine rather than of this
    second. That is why this is read here and not derived from the interrupt
    counters node_exporter already publishes.

    total is None when /proc/irq holds nothing, which is how a caller tells a
    machine with no interrupts to report from one whose /proc could not be
    read.
    """
    root = os.path.join(proc_path, "irq")
    numbers = sorted(
        (int(entry) for entry in _listdir(root) if entry.isdigit())
    )
    if not numbers:
        return {"total": None, "on_isolated": 0, "detail": []}

    isolated = set(isolated)
    if not isolated:
        return {"total": len(numbers), "on_isolated": 0, "detail": []}

    detail = []
    on_isolated = 0
    for number in numbers:
        entry = os.path.join(root, str(number))
        raw = _read(entry, "smp_affinity_list")
        if not raw:
            continue
        overlap = sorted(isolated.intersection(parse_cpu_list(raw)))
        if not overlap:
            continue
        on_isolated += 1
        if len(detail) < IRQ_DETAIL_LIMIT:
            detail.append({
                "irq": str(number),
                "name": _irq_name(entry),
                "cpus": overlap,
            })
    return {"total": len(numbers), "on_isolated": on_isolated, "detail": detail}


def _irq_name(entry: str) -> str:
    """The device behind an interrupt, which is the only useful part of it.

    /proc/irq/<n>/ holds one subdirectory named after the handler. A number
    alone tells an operator nothing, and the name is what says whether an
    interrupt on an isolated CPU is the storage controller or a USB port
    nobody uses.
    """
    for child in sorted(_listdir(entry)):
        if os.path.isdir(os.path.join(entry, child)):
            return child
    return ""


def _listdir(path: str) -> list:
    try:
        return os.listdir(path)
    except OSError:
        return []


def collect(isolated=(), proc_path: str = "/proc", sys_path: str = "/sys",
            etc_path: str = "/etc", usr_path: str = "/usr") -> dict:
    """Every reading above, in one dict, for the exporter to publish.

    isolated is passed in rather than read again: the exporter already has the
    topology, and reading /sys/devices/system/cpu/isolated a second time could
    only disagree with it.
    """
    return {
        "tuned": tuned_profile(etc_path, usr_path),
        "cmdline": kernel_cmdline(proc_path),
        "sched_rt": sched_rt(proc_path),
        "hugepages": hugepages(sys_path),
        "thp": transparent_hugepages(sys_path),
        "smt": smt(sys_path),
        "acpi": acpi_present(sys_path),
        "irq": irq_affinity(isolated, proc_path),
    }
