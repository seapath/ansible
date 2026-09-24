# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Apply CPU affinity and scheduler policy to QEMU threads.

Order of application: vCPUs, emulator, vhost, iothreads.

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

# Both tools return at once; a hang would hold the pool flock and libvirt's
# start job with it.
_TIMEOUT = 5


def _run(cmd: list, what: str):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"{what}: {exc}") from exc
    if r.returncode != 0:
        raise RuntimeError(f"{what}: {r.stderr.strip()}")


def _taskset(tid: int, cpus: list):
    cpu_str = format_cpu_list(cpus)
    _run(["taskset", "-cp", cpu_str, str(tid)], f"taskset -cp {cpu_str} {tid}")


def _chrt(tid: int, scheduler: str, priority: int):
    flag = CHRT_FLAG.get(scheduler.upper(), "-o")
    _run(["chrt", flag, "-p", str(priority), str(tid)],
         f"chrt {flag} -p {priority} {tid}")


def _apply_one(tid: int, alloc: GroupAllocation) -> str:
    """Apply one allocation to one thread; return the failure, or ''."""
    if alloc.cpus:
        try:
            _taskset(tid, alloc.cpus)
        except RuntimeError as exc:
            log.error("affinity failed for %s tid=%d: %s", alloc.name, tid, exc)
            return f"{alloc.name} tid={tid}: affinity failed: {exc}"
    elif alloc.scheduler.upper() not in ("FIFO", "RR"):
        # isolation=none with a non-RT scheduler: the thread already runs with
        # default (housekeeping) affinity and default policy. Nothing to apply.
        return ""
    # No cores but an RT scheduler (isolation: none + FIFO/RR): the thread
    # stays on its default housekeeping affinity but still gets the requested
    # RT policy.
    try:
        _chrt(tid, alloc.scheduler, alloc.priority)
    except RuntimeError as exc:
        log.error("scheduler failed for %s tid=%d: %s", alloc.name, tid, exc)
        return f"{alloc.name} tid={tid}: scheduler failed: {exc}"
    return ""


def apply_all(threads: QemuThreads, allocations: List[GroupAllocation]) -> List[str]:
    """
    Apply allocations to QEMU threads in the required order.

    Returns the failures, one line per thread, so that the caller can
    report them as degradations.
    """
    by_name = {a.name: a for a in allocations}
    work = []

    for n, tid in sorted(threads.vcpus.items()):
        work.append((tid, by_name.get(f"vcpu/{n}")))

    work.append((threads.emulator_tid, by_name.get("emulator")))

    vhost_group = by_name.get("vhost")
    for i, tid in enumerate(threads.vhost_tids):
        work.append((tid, vhost_group or by_name.get(f"vhost/{i}")))

    iothread_group = by_name.get("iothread")
    for i, tid in enumerate(threads.iothread_tids):
        work.append((tid, iothread_group or by_name.get(f"iothread/{i}")))

    failures = []
    for tid, alloc in work:
        if alloc:
            failure = _apply_one(tid, alloc)
            if failure:
                failures.append(failure)
    return failures
