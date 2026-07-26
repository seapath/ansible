# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Apply CPU affinity and scheduler policy to QEMU threads.

Order of application: vCPUs → emulator → vhost → iothreads.

The ordering constraint comes from how vhost kernel threads work: they are
created by the kernel when the guest activates a virtio queue, and they
inherit the CPU affinity of whatever thread triggered their creation
(usually the emulator thread). If we pin the emulator before any new vhost
threads appear, those threads will inherit the correct affinity. We still
re-pin any existing vhost threads explicitly afterward to handle threads
that existed before our hook ran.
"""

import logging
import subprocess
from typing import List

from .allocator import GroupAllocation
from .threads import QemuThreads
from .topology import format_cpu_list

log = logging.getLogger(__name__)

CHRT_FLAG = {"FIFO": "-f", "RR": "-r", "OTHER": "-o", "BATCH": "-b"}


def _taskset(tid: int, cpus: list):
    cpu_str = format_cpu_list(cpus)
    r = subprocess.run(
        ["taskset", "-cp", cpu_str, str(tid)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"taskset -cp {cpu_str} {tid}: {r.stderr.strip()}")


def _chrt(tid: int, scheduler: str, priority: int):
    flag = CHRT_FLAG.get(scheduler.upper(), "-o")
    r = subprocess.run(
        ["chrt", flag, "-p", str(priority), str(tid)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"chrt {flag} -p {priority} {tid}: {r.stderr.strip()}")


def _apply_one(tid: int, alloc: GroupAllocation):
    if alloc.cpus:
        try:
            _taskset(tid, alloc.cpus)
        except RuntimeError as exc:
            log.error("affinity failed for %s tid=%d: %s", alloc.name, tid, exc)
            return
    elif alloc.scheduler.upper() not in ("FIFO", "RR"):
        # isolation=none with a non-RT scheduler: the thread already runs with
        # default (housekeeping) affinity and default policy. Nothing to apply.
        return
    # No cores but an RT scheduler (isolation: none + FIFO/RR): the thread
    # stays on its default housekeeping affinity but still gets the requested
    # RT policy.
    try:
        _chrt(tid, alloc.scheduler, alloc.priority)
    except RuntimeError as exc:
        log.error("scheduler failed for %s tid=%d: %s", alloc.name, tid, exc)


def apply_all(threads: QemuThreads, allocations: List[GroupAllocation]):
    """Apply allocations to QEMU threads in the required order."""
    by_name = {a.name: a for a in allocations}

    for i, tid in enumerate(threads.vcpu_tids):
        alloc = by_name.get(f"vcpu/{i}")
        if alloc:
            _apply_one(tid, alloc)

    alloc = by_name.get("emulator")
    if alloc:
        _apply_one(threads.emulator_tid, alloc)

    vhost_group = by_name.get("vhost")
    for i, tid in enumerate(threads.vhost_tids):
        alloc = vhost_group or by_name.get(f"vhost/{i}")
        if alloc:
            _apply_one(tid, alloc)

    iothread_group = by_name.get("iothread")
    for i, tid in enumerate(threads.iothread_tids):
        alloc = iothread_group or by_name.get(f"iothread/{i}")
        if alloc:
            _apply_one(tid, alloc)
