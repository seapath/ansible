# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
QEMU process and thread discovery via /proc.

libvirt does not pass the QEMU PID to the hook, so we scan /proc/*/cmdline
looking for a process whose binary contains "qemu" and whose arguments
contain "-name guest=<vm_name>". Once the PID is known we read
/proc/<pid>/task/ to classify every thread by its comm name, as QEMU
names them with debug-threads=on (always set by libvirt):

  CPU <n>/KVM       vCPU n
  IO iothread<n>    iothread object iothread<n> (libvirt ids)
  vhost-<pid>       vhost worker: a QEMU thread from Linux 6.4, a kernel
                    thread of its own (outside /proc/<pid>/task) before

Discovery happens in two phases:
  1. Poll until all expected vCPU threads are visible.
  2. Short grace period for vhost threads to appear.
     Their count depends on the number of virtio queues configured, not on
     the vCPU count: we take whatever is visible when the count stabilizes.
"""

import glob
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_POLL_INTERVAL = 0.1   # seconds between /proc scans
_DEFAULT_TIMEOUT = 5.0  # max total wait for vCPU threads
_VHOST_GRACE = 0.5     # extra wait after vCPUs found, for vhost to appear


_VCPU_RE = re.compile(r'^CPU (\d+)/KVM$')
_IOTHREAD_RE = re.compile(r'^IO iothread(\d+)$')


@dataclass
class QemuThreads:
    pid: int
    emulator_tid: int
    # {vCPU index: tid}, the index read from the thread name: TID order says
    # nothing once TIDs wrap or a vCPU is hot-plugged.
    vcpus: Dict[int, int] = field(default_factory=dict)
    vhost_tids: List[int] = field(default_factory=list)
    # {iothread id: tid}
    iothreads: Dict[int, int] = field(default_factory=dict)

    @property
    def vcpu_tids(self) -> List[int]:
        return [self.vcpus[n] for n in sorted(self.vcpus)]

    @property
    def iothread_tids(self) -> List[int]:
        return [self.iothreads[n] for n in sorted(self.iothreads)]


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
        binary = args[0].decode('utf-8', errors='replace')
        if 'qemu' not in binary:
            continue
        full = raw.decode('utf-8', errors='replace')
        if target.search(full):
            return int(os.path.basename(pid_dir))
    return None


def _kernel_vhost_tids(pid: int, proc_path: str = "/proc") -> List[int]:
    """
    vhost workers of pid that run as kernel threads (Linux before 6.4).

    They are processes of their own named "vhost-<qemu_pid>", so finding
    them takes a scan of every /proc/<pid>/comm.
    """
    target = f"vhost-{pid}"
    tids = []
    for comm_path in glob.glob(os.path.join(proc_path, "[0-9]*", "comm")):
        try:
            with open(comm_path) as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm == target:
            tids.append(int(os.path.basename(os.path.dirname(comm_path))))
    return tids


def _classify_threads(pid: int, proc_path: str = "/proc",
                      kernel_vhost: bool = False) -> QemuThreads:
    """
    Read /proc/<pid>/task/ and classify each thread by its comm.

    kernel_vhost also looks for vhost kernel threads outside the process,
    a scan of the whole /proc that discover() only does once the vCPUs are
    up.
    """
    result = QemuThreads(pid=pid, emulator_tid=pid)
    task_dir = os.path.join(proc_path, str(pid), "task")
    try:
        tid_names = os.listdir(task_dir)
    except OSError:
        tid_names = []

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

        vcpu_m = _VCPU_RE.match(comm)
        iothread_m = _IOTHREAD_RE.match(comm)
        if vcpu_m:
            result.vcpus[int(vcpu_m.group(1))] = tid
        elif comm == f"vhost-{pid}":
            result.vhost_tids.append(tid)
        elif iothread_m:
            result.iothreads[int(iothread_m.group(1))] = tid

    if kernel_vhost:
        # readdir of /proc lists processes only, so a user vhost thread found
        # above never shows up here a second time.
        result.vhost_tids.extend(_kernel_vhost_tids(pid, proc_path))

    result.vhost_tids.sort()
    return result


def discover(vm_name: str,
             expected_vcpus: int = 1,
             proc_path: str = "/proc",
             timeout: float = _DEFAULT_TIMEOUT) -> Optional[QemuThreads]:
    """
    Find all QEMU threads for vm_name.

    Phase 1: wait for all vCPU threads (exact count known).
    Phase 2: short grace period for vhost threads to appear and stabilize.
      Vhost workers are created when virtio queues activate;
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
    threads = _classify_threads(pid, proc_path, kernel_vhost=True)
    while time.monotonic() < grace_end:
        time.sleep(_POLL_INTERVAL)
        updated = _classify_threads(pid, proc_path, kernel_vhost=True)
        if (updated.vhost_tids and
                len(updated.vhost_tids) == len(threads.vhost_tids)):
            threads = updated
            break
        threads = updated

    return threads
