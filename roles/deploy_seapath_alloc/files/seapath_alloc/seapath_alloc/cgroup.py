# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Cgroup utility helpers shared by seapath-container-pin, seapath-container-unpin,
and the repacker.
"""

import logging
import os
import subprocess

from .applier import CHRT_FLAG

log = logging.getLogger(__name__)


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


def cgroup_procs(root: str) -> list:
    """Return all PIDs in a cgroup tree."""
    pids = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if "cgroup.procs" in filenames:
            try:
                with open(os.path.join(dirpath, "cgroup.procs")) as f:
                    pids.extend(int(line) for line in f if line.strip())
            except OSError:
                pass
    return pids


def apply_cpuset(root: str, cpu_str: str) -> None:
    """Write cpu_str to cpuset.cpus at every level of the cgroup tree."""
    for dirpath, _dirnames, filenames in os.walk(root, topdown=True):
        if "cpuset.cpus" in filenames:
            try:
                with open(os.path.join(dirpath, "cpuset.cpus"), "w") as f:
                    f.write(cpu_str)
            except OSError as exc:
                log.warning("cpuset %s: %s", dirpath, exc)


def taskset_procs(pids: list, cpu_str: str) -> None:
    """Apply taskset to a list of PIDs."""
    for pid in pids:
        subprocess.run(
            ["taskset", "-cp", cpu_str, str(pid)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def chrt_procs(pids: list, scheduler: str, priority: int) -> None:
    """Apply chrt to a list of PIDs."""
    flag = CHRT_FLAG.get(scheduler, "-o")
    for pid in pids:
        subprocess.run(
            ["chrt", flag, "-p", str(priority), str(pid)],
            check=False,
            stderr=subprocess.DEVNULL,
        )
