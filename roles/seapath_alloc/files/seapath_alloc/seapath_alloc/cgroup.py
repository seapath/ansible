# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Cgroup utility helpers shared by seapath-container-pin, seapath-container-unpin,
and the repacker.

A quadlet service runs `podman run --cgroups=split`, which splits its cgroup
into conmon's `runtime/` sub-cgroup and the container's `libpod-payload-<id>/`
sub-cgroup (plus systemd's `.control/` for ExecStartPost= and friends).  Only
the payload is the real-time workload: it gets the allocated cores and the
scheduling policy, and every other sub-cgroup is confined to the housekeeping
cores.  A service without a payload sub-cgroup (not podman, or another cgroup
mode) is treated as a whole: every level gets the allocated cores and every
thread gets the policy.

Policy and affinity are applied per thread, from cgroup.threads: sched_setscheduler
and sched_setaffinity only act on the thread they name, and threads the
workload started before the pin would otherwise keep their old values.
"""

import logging
import os
import subprocess

from .topology import format_cpu_list, parse_cpu_list

log = logging.getLogger(__name__)

PAYLOAD_PREFIX = "libpod-payload-"

SCHED_POLICY = {
    "FIFO": os.SCHED_FIFO,
    "RR": os.SCHED_RR,
    "OTHER": os.SCHED_OTHER,
    # Linux only; the fallback lets the module import on a dev workstation.
    "BATCH": getattr(os, "SCHED_BATCH", 3),
}

# Threads started while the policy is being applied inherit from their
# creator, which may not have been reached yet: re-read cgroup.threads until
# no new thread shows up, a few passes at most.
POLICY_PASSES = 3


def cgroup_root(service: str) -> str | None:
    """Return the /sys/fs/cgroup path for a systemd service, or None."""
    try:
        cgroup = subprocess.check_output(
            ["systemctl", "show", "--property=ControlGroup", "--value", service],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    return f"/sys/fs/cgroup{cgroup}" if cgroup else None


def _read_ids(path: str) -> list:
    try:
        with open(path) as f:
            return [int(line) for line in f if line.strip()]
    except OSError:
        return []


def cgroup_procs(root: str) -> list:
    """Return all PIDs in a cgroup tree."""
    pids = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "cgroup.procs" in filenames:
            pids.extend(_read_ids(os.path.join(dirpath, "cgroup.procs")))
    return pids


def cgroup_threads(dirs: list) -> list:
    """Return the TIDs listed in cgroup.threads of each directory (not recursive)."""
    tids = []
    for d in dirs:
        tids.extend(_read_ids(os.path.join(d, "cgroup.threads")))
    return tids


def service_cgroups(root: str) -> tuple:
    """
    Split a service cgroup tree into (payload, rest) directory lists.

    payload holds every directory at or below a libpod-payload-* cgroup, rest
    every other directory below root.  root itself is in neither.  payload is
    empty when the service is not a podman container with split cgroups.
    """
    payload, rest = [], []
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames.sort()
        if dirpath == root:
            continue
        rel = os.path.relpath(dirpath, root).split(os.sep)
        if any(part.startswith(PAYLOAD_PREFIX) for part in rel):
            payload.append(dirpath)
        else:
            rest.append(dirpath)
    return payload, rest


def _write_cpuset(dirpath: str, cpu_str: str) -> None:
    try:
        with open(os.path.join(dirpath, "cpuset.cpus"), "w") as f:
            f.write(cpu_str)
    except OSError as exc:
        # A sub-cgroup can vanish mid-walk (container exiting): not fatal.
        log.warning("cpuset %s: %s", dirpath, exc)


def _read_cpuset(dirpath: str) -> list:
    try:
        with open(os.path.join(dirpath, "cpuset.cpus")) as f:
            return parse_cpu_list(f.read().strip())
    except OSError:
        return []


def set_affinity(tids: list, cpus: list) -> None:
    """sched_setaffinity on each thread; a vanished thread is skipped."""
    for tid in tids:
        try:
            os.sched_setaffinity(tid, cpus)
        except ProcessLookupError:
            log.debug("affinity: thread %d is gone", tid)
        except OSError as exc:
            log.warning("affinity %s on thread %d: %s",
                        format_cpu_list(cpus), tid, exc)


def set_policy(tids: list, scheduler: str, priority: int) -> None:
    """sched_setscheduler on each thread; a vanished thread is skipped."""
    policy = SCHED_POLICY.get(scheduler, SCHED_POLICY["OTHER"])
    for tid in tids:
        try:
            os.sched_setscheduler(tid, policy, os.sched_param(priority))
        except ProcessLookupError:
            log.debug("policy: thread %d is gone", tid)
        except OSError as exc:
            log.warning("policy %s/%d on thread %d: %s",
                        scheduler, priority, tid, exc)


def place_service(root: str, cpus: list, housekeeping: list) -> None:
    """
    Write the cpusets of a service tree and the affinity of its threads.

    With a payload sub-cgroup: the payload gets cpus, the rest (conmon,
    .control) the housekeeping cores, and the service root both, since a
    cgroup v2 child only gets the CPUs its parent also has.  Without one, or
    without known housekeeping cores, every level and thread gets cpus.
    """
    payload, rest = service_cgroups(root)
    cpu_str = format_cpu_list(cpus)
    if not payload or not housekeeping:
        for d in [root] + rest + payload:
            _write_cpuset(d, cpu_str)
        set_affinity(cgroup_threads([root] + rest + payload), cpus)
        return

    outer = sorted(set(cpus) | set(housekeeping))
    # Grow the root before narrowing the children and shrink it after: on a
    # move, a payload asking for a CPU its parent lacks would fall back to the
    # parent's whole set, housekeeping included, for the time in between.
    _write_cpuset(root, format_cpu_list(set(_read_cpuset(root)) | set(outer)))
    for d in payload:
        _write_cpuset(d, cpu_str)
    for d in rest:
        _write_cpuset(d, format_cpu_list(housekeeping))
    _write_cpuset(root, format_cpu_list(outer))

    set_affinity(cgroup_threads(payload), cpus)
    set_affinity(cgroup_threads(rest), housekeeping)


def schedule_payload(root: str, scheduler: str, priority: int) -> list:
    """
    Apply the scheduling policy to every thread of the payload.

    The payload is the libpod-payload-* sub-cgroups when there are any, the
    whole tree otherwise.  Returns the TIDs the policy was applied to.
    """
    payload, rest = service_cgroups(root)
    dirs = payload or [root] + rest
    done: list = []
    for _ in range(POLICY_PASSES):
        seen = set(done)
        new = [t for t in cgroup_threads(dirs) if t not in seen]
        if not new:
            break
        set_policy(new, scheduler, priority)
        done.extend(new)
    return done
