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
from .config import _ISOLATIONS, _SCHEDULERS, _normalize_group
from .pool import CorePool
from .scheduler import allocate_cores
from .topology import Topology, format_cpu_list

try:
    import yaml
except ImportError:
    yaml = None

log = logging.getLogger(__name__)

# taskset and chrt return at once; a hang would hold up the caller.
_TIMEOUT = 5


class ClaimError(Exception):
    """A claim that cannot be made or applied."""


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


def parse_isolation_spec(value: str):
    """
    Parse a positional CLI isolation argument, as parse_isolation_arg, where
    a plain level may also give a number of cores: "exclusive_logical:2",
    "exclusive_physical:2". A slot's size is the slot's, never given here.

    Returns (isolation, slot_name, count).
    Raises ValueError on an empty slot name or a count that is not a
    positive integer.
    """
    isolation, slot = parse_isolation_arg(value)
    if slot:
        return isolation, slot, 1
    level, sep, raw = value.partition(":")
    if not sep:
        return level, "", 1
    try:
        count = int(raw)
    except ValueError:
        raise ValueError(f"core count must be an integer in {value!r}") from None
    if count < 1:
        raise ValueError(f"core count must be at least 1 in {value!r}")
    return level, "", count


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


def _run(cmd: list):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ClaimError(f"{' '.join(cmd)}: {exc}") from exc
    if r.returncode != 0:
        raise ClaimError(f"{' '.join(cmd)}: {r.stderr.strip()}")


def _apply(pid: int, alloc):
    """Pin and schedule every thread of pid (-a), as the allocation says."""
    if alloc.cpus:
        _run(["taskset", "-a", "-cp", format_cpu_list(alloc.cpus), str(pid)])
    # isolation=none still honours an RT scheduler request: the process
    # keeps its default housekeeping affinity but gets the RT policy.
    if alloc.cpus or alloc.scheduler.upper() in ("FIFO", "RR"):
        flag = CHRT_FLAG.get(alloc.scheduler.upper(), "-o")
        _run(["chrt", "-a", flag, "-p", str(alloc.priority), str(pid)])


def _check_request(isolation, scheduler, priority):
    """
    Validate a request given on the command line, which, unlike a profile,
    has an operator waiting for the answer: a value the allocator or chrt
    would not honour is an error, so the workload is not started believing
    it runs real time.
    """
    if isolation not in _ISOLATIONS:
        raise ClaimError(f"unknown isolation {isolation!r}"
                         f" (expected one of {', '.join(_ISOLATIONS)})")
    sched = str(scheduler).upper()
    # APP places the cores and leaves each thread's policy to the
    # application (seapath-container-pin).
    accepted = _SCHEDULERS + ("APP",)
    if sched not in accepted:
        raise ClaimError(f"unknown scheduler {scheduler!r}"
                         f" (expected one of {', '.join(accepted)})")
    try:
        prio = int(priority)
    except (TypeError, ValueError):
        raise ClaimError(f"priority must be an integer, got {priority!r}") from None
    if sched in ("FIFO", "RR") and not 1 <= prio <= 99:
        raise ClaimError(f"{sched} priority must be within 1-99, got {prio}")
    if sched in ("OTHER", "BATCH", "APP") and prio != 0:
        raise ClaimError(f"{sched} priority must be 0, got {prio}")
    return sched, prio


def claim_allocation(label: str,
                     isolation: str = "exclusive_logical",
                     scheduler: str = "OTHER",
                     priority: int = 0,
                     profile_path: str = "",
                     target_pid: int = 0,
                     no_apply: bool = False,
                     kind: str = "",
                     slot: str = "",
                     count: int = 1):
    """
    Allocate isolated cores for label and register the claim.

    Unless no_apply is True, also applies the allocation to every thread of
    target_pid (or of the calling process if target_pid is 0) via taskset +
    chrt. A failure to apply it removes the claim and raises ClaimError: the
    caller must not run a real-time workload believing it is pinned.

    A label held by another live process is refused with ClaimError; the
    same process claiming again replaces its own claim.

    slot: name of a host-global shared-core slot. The claim then joins the
    slot's cores (creating the slot if needed, with `isolation` as the slot's
    level) instead of consuming its own cores.

    count: how many cores the claim takes for itself, of its isolation
    level (logical CPUs, or physical pairs), without a slot. The process
    may use them all and places its own threads among them; the repacker
    never moves a claim of several cores.

    Returns the GroupAllocation: its scheduler and priority are the ones
    applied, which differ from the request after a hard fallback.
    """
    pid = target_pid or os.getpid()
    topo = Topology()

    if profile_path:
        raw = _load_profile_file(profile_path)
        merged = {"isolation": raw.get("isolation", isolation),
                  "scheduler": raw.get("scheduler", scheduler),
                  "priority": raw.get("priority", priority)}
        if raw.get("slot", slot):
            merged["slot"] = raw.get("slot", slot)
        # A profile file is validated like a VM profile: a typo is logged
        # rather than handed to chrt.
        merged = _normalize_group(merged, f"profile {profile_path}")
        isolation = merged["isolation"]
        scheduler = merged["scheduler"]
        priority = merged["priority"]
        slot = merged.get("slot", "")
    else:
        scheduler, priority = _check_request(isolation, scheduler, priority)

    spec_dict = {"name": "claim", "isolation": isolation,
                 "scheduler": scheduler, "priority": priority}
    if slot:
        spec_dict["slot"] = slot
    elif count > 1:
        spec_dict["count"] = count

    with CorePool(topology=topo) as pool:
        for existing in pool.all_claims():
            if (existing.get("label") == label and existing.get("pid")
                    and existing["pid"] != pid):
                raise ClaimError(f"label {label!r} is held by live pid"
                                 f" {existing['pid']}")
        result = allocate_cores(pool, [spec_dict], topo, label=label, pid=pid)
        alloc = result.allocations[0]
        # Only record the slot if it actually exists after allocation: a
        # creation that fell back to housekeeping does not persist the slot.
        in_slot = slot if any(s["name"] == slot for s in pool.slots()) else ""
        pool.add_claim(label, pid, alloc.cpus, alloc.scheduler, alloc.priority,
                       kind=kind, slot=in_slot)

    if not no_apply:
        try:
            _apply(pid, alloc)
        except ClaimError:
            with CorePool(topology=topo) as pool:
                pool.remove_claim(label)
            raise

    return alloc


def claim(*args, **kwargs) -> list:
    """claim_allocation(), returning the list of allocated cores only."""
    return claim_allocation(*args, **kwargs).cpus


def release(label: str, pid: int = 0) -> bool:
    """
    Remove the claim for label. With pid, only when the claim is that
    process's: a label taken over by another process stays.

    Returns True when a claim was removed. The threads of the other actors
    stay where they are: moving them is left to `seapath-alloc spread`.
    """
    with CorePool() as pool:
        claims = [c for c in pool.all_claims() if c.get("label") == label]
        if pid and any(c.get("pid") != pid for c in claims):
            log.warning("claim %r belongs to another process, not released", label)
            return False
        if not claims:
            return False
        pool.remove_claim(label)
        return True
