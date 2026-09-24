# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
libvirt QEMU hook entry point.

libvirt calls every script in /etc/libvirt/hooks/qemu.d/ on every VM
lifecycle event, passing four arguments:
  <vm-name>  <operation>  <sub-operation>  <extra>

We act only on "started begin": a normal VM start, and also the arrival
of a live migration (libvirt runs the same "started begin" on the
destination host once the domain is running there).

All other events are ignored (exit 0 immediately).

CRITICAL: this script must ALWAYS exit 0. A non-zero exit causes libvirt to
abort the VM operation. If pinning fails, the VM starts without RT
guarantees and the error is logged.
"""

import logging
import sys
import xml.etree.ElementTree as ET

from .allocator import AllocationEngine
from .applier import apply_all
from .config import expand_group_specs, get_vcpu_count, load_profile
from .logging_setup import setup_logging
from .pool import CorePool
from .scheduler import allocate_cores
from .threads import discover
from .topology import Topology

log = logging.getLogger(__name__)

_TRIGGER_EVENTS = {("started", "begin")}

_STATIC_PINS = ("vcpupin", "emulatorpin", "iothreadpin")


def _has_static_pinning(domain_xml: str) -> bool:
    """True when the domain XML pins threads itself through <cputune>."""
    try:
        root = ET.fromstring(domain_xml)
    except ET.ParseError:
        return False
    return any(root.find(f"cputune/{tag}") is not None for tag in _STATIC_PINS)


def handle_start(vm_name: str, domain_xml: str = ""):
    """Allocate cores and apply pinning for vm_name."""
    topo = Topology()
    profile = load_profile(vm_name, domain_xml=domain_xml)
    vcpu_count = get_vcpu_count(vm_name, domain_xml=domain_xml)

    # Discovery polls /proc for up to a few seconds and reads no pool state:
    # it runs before the flock, so that the VMs started together at node boot
    # do not wait on each other's polls.
    threads = discover(vm_name, expected_vcpus=vcpu_count)
    if threads is None:
        log.error("VM %s: QEMU process not found, pinning skipped", vm_name)
        return

    specs = expand_group_specs(
        profile,
        vcpu_count=vcpu_count,
        vhost_count=len(threads.vhost_tids),
        iothread_count=len(threads.iothread_tids),
    )

    if not any(s.get("isolation", "none") != "none" for s in specs):
        # Nothing to place on isolated cores: no pool, no flock. A group with
        # isolation none and an RT scheduler still gets its policy.
        engine = AllocationEngine([], [], topo.housekeeping_cpus(), topo.siblings_of)
        failures = apply_all(threads, engine.allocate(specs).allocations)
    else:
        if _has_static_pinning(domain_xml):
            log.warning(
                "VM %s: <cputune> pins threads and a seapath_alloc profile is"
                " set: the profile overrides the static pinning, use one or"
                " the other", vm_name)
        with CorePool(topology=topo) as pool:
            # Allocation AND application both happen inside the flock. A
            # VM's chosen cores are not persisted anywhere: busy accounting is
            # derived from /proc affinities, which only reflect our decision
            # once taskset has run. Releasing the lock before applying would
            # let a concurrent hook read /proc, see our cores as still free
            # (threads not yet pinned), and double-allocate them.
            result = allocate_cores(
                pool, specs, topo,
                exclude_pids={threads.pid},
                label=f"VM {vm_name}",
                pid=threads.pid,
            )
            failures = apply_all(threads, result.allocations)

    if failures:
        log.error("VM %s: pinning applied with %d failure(s): %s",
                  vm_name, len(failures), "; ".join(failures))
    else:
        log.info(
            "VM %s: pinning applied (%d vcpu, %d vhost, %d iothread)",
            vm_name, vcpu_count, len(threads.vhost_tids), len(threads.iothread_tids),
        )


def main():
    setup_logging()

    if len(sys.argv) < 4:
        log.debug("hook called with too few arguments: %s", sys.argv)
        sys.exit(0)

    vm_name, operation, sub_op = sys.argv[1], sys.argv[2], sys.argv[3]
    log.debug("hook: vm=%s op=%s sub=%s", vm_name, operation, sub_op)

    if (operation, sub_op) not in _TRIGGER_EVENTS:
        sys.exit(0)

    # libvirt passes the full domain XML on stdin for every hook invocation.
    # Reading it here avoids any virsh subprocess calls inside the hook, which
    # would fail when the hook environment doesn't inherit the libvirt socket URI.
    domain_xml = sys.stdin.read()

    try:
        handle_start(vm_name, domain_xml=domain_xml)
    except Exception:
        log.exception(
            "VM %s: pinning failed (VM will start without RT guarantees)", vm_name
        )

    sys.exit(0)
