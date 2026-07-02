# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
seapath-alloc claim / release — logic layer.

claim:   allocate isolated cores and register them for a named actor
release: remove the claim
"""

import logging
import os
import subprocess

from .applier import CHRT_FLAG
from .pool import CorePool
from .scheduler import allocate_cores
from .topology import Topology, format_cpu_list

try:
    import yaml
except ImportError:
    yaml = None

log = logging.getLogger(__name__)


def parse_isolation_arg(value: str):
    """
    Parse a positional CLI isolation argument, which is either a plain
    isolation level or a slot reference "slot:<name>[:<isolation>]".

    Returns (isolation, slot_name); slot_name is "" for plain levels.
    Raises ValueError on an empty slot name.
    """
    if not value.startswith("slot:"):
        return value, ""
    name, _, isolation = value[len("slot:"):].partition(":")
    if not name:
        raise ValueError(f"empty slot name in {value!r}")
    return (isolation or "exclusive_logical"), name


def _load_profile_file(path: str) -> dict:
    if yaml is None:
        log.warning("pyyaml not available, ignoring profile file %s", path)
        return {}
    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("could not load profile %s: %s", path, exc)
        return {}


def claim(label: str,
          isolation: str = "exclusive_logical",
          scheduler: str = "OTHER",
          priority: int = 0,
          profile_path: str = "",
          target_pid: int = 0,
          no_apply: bool = False,
          kind: str = "",
          slot: str = "") -> list:
    """
    Allocate isolated cores for label and register the claim.

    Unless no_apply is True, also applies the allocation to target_pid
    (or the calling process if target_pid is 0) via taskset + chrt.

    slot: name of a host-global shared-core slot. The claim then joins the
    slot's cores (creating the slot if needed, with `isolation` as the slot's
    level) instead of consuming its own cores.

    Returns the list of allocated cores.
    """
    pid = target_pid or os.getpid()
    topo = Topology()

    if profile_path:
        raw = _load_profile_file(profile_path)
        isolation = raw.get("isolation", isolation)
        scheduler = raw.get("scheduler", scheduler)
        priority = raw.get("priority", priority)
        slot = raw.get("slot", slot)

    spec_dict = {"name": "claim", "isolation": isolation,
                 "scheduler": scheduler, "priority": priority}
    if slot:
        spec_dict["slot"] = slot

    with CorePool(topology=topo) as pool:
        result = allocate_cores(pool, [spec_dict], topo, label=label, pid=pid)
        alloc = result.allocations[0]
        # Only record the slot if it actually exists after allocation — a
        # creation that fell back to housekeeping does not persist the slot.
        in_slot = slot if any(s["name"] == slot for s in pool.slots()) else ""
        pool.add_claim(label, pid, alloc.cpus, alloc.scheduler, alloc.priority,
                       kind=kind, slot=in_slot)

    if not no_apply:
        if alloc.cpus:
            cpu_str = format_cpu_list(alloc.cpus)
            subprocess.run(["taskset", "-cp", cpu_str, str(pid)], check=False)
        # isolation=none still honours an RT scheduler request: the process
        # keeps its default housekeeping affinity but gets the RT policy.
        if alloc.cpus or alloc.scheduler.upper() in ("FIFO", "RR"):
            flag = CHRT_FLAG.get(alloc.scheduler.upper(), "-o")
            subprocess.run(["chrt", flag, "-p", str(alloc.priority), str(pid)], check=False)

    return alloc.cpus


def release(label: str):
    """Remove the claim for label."""
    from .allocator import AllocationStrategy
    from .config import load_strategy
    from .repacker import execute_repack, find_spread_moves

    with CorePool() as pool:
        pool.remove_claim(label)
        if load_strategy() == AllocationStrategy.REPACKING:
            moves = find_spread_moves(pool)
            if moves:
                log.info("spread after release of %r: %d move(s)", label, len(moves))
                # pool= is required so quadlet (CgroupMove) spreads update
                # claims.json; without it the claim keeps pointing at the old
                # CPU and the new one looks free → later double-allocation.
                execute_repack(moves, pool=pool)
                pool.bust_cache()


