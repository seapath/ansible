# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
QEMU process and thread discovery via /proc.

libvirt does not pass the QEMU PID to the hook, so we scan /proc/*/cmdline
looking for a process whose binary contains "qemu" and whose arguments
contain "-name guest=<vm_name>". Once the PID is known we read
/proc/<pid>/task/ to classify every thread by its comm name.

Discovery happens in two phases:
  1. Poll until all expected vCPU threads are visible.
  2. Short grace period for vhost threads to appear.
     Their count depends on the number of virtio queues configured, not on
     the vCPU count — we take whatever is visible when the count stabilizes.
"""

import glob
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger(__name__)

_POLL_INTERVAL = 0.1   # seconds between /proc scans
_DEFAULT_TIMEOUT = 5.0  # max total wait for vCPU threads
_VHOST_GRACE = 0.5     # extra wait after vCPUs found, for vhost to appear


@dataclass
class QemuThreads:
    pid: int
    emulator_tid: int
    vcpu_tids: List[int] = field(default_factory=list)
    vhost_tids: List[int] = field(default_factory=list)
    iothread_tids: List[int] = field(default_factory=list)


def find_qemu_pid(vm_name: str, proc_path: str = "/proc") -> Optional[int]:
    """
    Scan /proc/*/cmdline for the QEMU process of vm_name.

    libvirt launches QEMU with '-name guest=<vm_name>,...' in its command
    line. We look for a process whose binary path contains 'qemu' and whose
    null-separated argument list contains that token.
    """
    # The VM name must be followed by a delimiter (or end of string): a bare
    # substring test would let "guest=vm" match the process of VM "vm2".
    target = re.compile(r'guest=' + re.escape(vm_name) + r'([,\x00 ]|$)')
    for pid_dir in glob.glob(os.path.join(proc_path, "[0-9]*")):
        try:
            with open(os.path.join(pid_dir, "cmdline"), 'rb') as f:
                raw = f.read()
        except OSError:
            continue
        args = raw.split(b'\x00')
        if not args:
            continue
        binary = args[0].decode('utf-8', errors='replace')
        if 'qemu' not in binary:
            continue
        full = raw.decode('utf-8', errors='replace')
        if target.search(full):
            return int(os.path.basename(pid_dir))
    return None


def _classify_threads(pid: int, proc_path: str = "/proc") -> QemuThreads:
    """Read /proc/<pid>/task/ and classify each thread by its comm."""
    result = QemuThreads(pid=pid, emulator_tid=pid)
    task_dir = os.path.join(proc_path, str(pid), "task")
    try:
        tid_names = os.listdir(task_dir)
    except OSError:
        return result

    for tid_str in tid_names:
        try:
            tid = int(tid_str)
        except ValueError:
            continue
        try:
            with open(os.path.join(task_dir, tid_str, "comm")) as f:
                comm = f.read().strip()
        except OSError:
            continue

        if re.match(r'^CPU \d+/KVM$', comm):
            result.vcpu_tids.append(tid)
        elif comm.startswith('vhost'):
            result.vhost_tids.append(tid)
        elif comm.startswith('iothread'):
            result.iothread_tids.append(tid)
        elif tid == pid:
            result.emulator_tid = tid

    result.vcpu_tids.sort()
    result.vhost_tids.sort()
    result.iothread_tids.sort()
    return result


def discover(vm_name: str,
             expected_vcpus: int = 1,
             proc_path: str = "/proc",
             timeout: float = _DEFAULT_TIMEOUT) -> Optional[QemuThreads]:
    """
    Find all QEMU threads for vm_name.

    Phase 1 — wait for all vCPU threads (exact count known).
    Phase 2 — short grace period for vhost threads to appear and stabilize.
      Vhost threads are kernel threads created when virtio queues activate;
      their count depends on the number of queues configured, not on vCPU
      count, so we wait for stabilization rather than a specific number.

    Returns None if the QEMU process cannot be found at all.
    """
    pid = find_qemu_pid(vm_name, proc_path)
    if pid is None:
        log.warning("no QEMU process for VM %s", vm_name)
        return None

    # Phase 1: wait for all vCPU threads.
    deadline = time.monotonic() + timeout
    threads = _classify_threads(pid, proc_path)
    while len(threads.vcpu_tids) < expected_vcpus:
        if time.monotonic() >= deadline:
            log.warning(
                "VM %s: %d/%d vCPU threads visible after %.1fs",
                vm_name, len(threads.vcpu_tids), expected_vcpus, timeout,
            )
            break
        time.sleep(_POLL_INTERVAL)
        threads = _classify_threads(pid, proc_path)

    # Phase 2: short grace for vhost threads to appear and stabilize.
    grace_end = min(time.monotonic() + _VHOST_GRACE, deadline)
    while time.monotonic() < grace_end:
        time.sleep(_POLL_INTERVAL)
        updated = _classify_threads(pid, proc_path)
        if (updated.vhost_tids and
                len(updated.vhost_tids) == len(threads.vhost_tids)):
            threads = updated
            break
        threads = updated

    return threads
