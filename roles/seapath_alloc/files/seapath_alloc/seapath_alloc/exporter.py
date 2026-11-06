# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Prometheus textfile collector for the seapath-alloc pool.

Writes to /var/lib/prometheus/node_exporter/seapath-alloc.prom using an
atomic rename so node_exporter never reads a partial file.

Run every 15 seconds via the seapath-alloc-export.timer systemd timer.

Persistent fallback state is kept in /var/lib/seapath/alloc/fallbacks.json
so counts survive reboots.
"""

import json
import logging
import os
import time

from .pool import process_start_time
from .status import collect
from .topology import Topology, parse_cpu_list

log = logging.getLogger(__name__)

_PROM_PATH   = "/var/lib/prometheus/node_exporter/seapath-alloc.prom"
_STATE_PATH  = "/var/lib/seapath/alloc/fallbacks.json"
_ACTIVE_PATH = "/var/lib/seapath/alloc/active_fallbacks.json"


# ---------------------------------------------------------------------------
# Fallback state persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    try:
        with open(_STATE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"total": 0, "last_ts": 0,
                "last_label": "", "last_group": "", "last_requested": "",
                "last_severity": ""}


def _load_active() -> dict:
    try:
        with open(_ACTIVE_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _entry_alive(entry: dict, proc_path: str = "/proc") -> bool:
    """
    Whether the process of an active entry still runs. As for a claim, the
    start time recorded next to the PID keeps a recycled PID from holding
    the entry alive.
    """
    pid = entry.get("pid")
    if not pid:
        return True
    if not os.path.exists(os.path.join(proc_path, str(pid))):
        return False
    recorded = entry.get("start")
    if recorded is None:
        return True
    start = process_start_time(pid, proc_path)
    return start is None or start == recorded


def _live(active: dict) -> dict:
    """The active entries whose process is still running."""
    return {k: e for k, e in active.items() if _entry_alive(e)}


def record_fallback(label: str, group: str, requested_isolation: str,
                    pid: int = 0, severity: str = "hard"):
    """
    Record a degradation event.

    severity="hard": no RT isolation (housekeeping cores, unknown isolation).
    severity="soft": RT isolation preserved with less than asked.

    Updates the cumulative counter in fallbacks.json and, when a PID is
    provided, tracks the actor as currently degraded in active_fallbacks.json.
    Entries of exited processes are pruned here, under the pool flock the
    allocation pipeline holds; the exporter only filters them out.

    This is monitoring: a state file that cannot be written is logged and
    never fails the allocation that is being recorded.
    """
    now = int(time.time())
    try:
        state = _load_state()
        state["total"] = state.get("total", 0) + 1
        state["last_ts"] = now
        state["last_label"] = label
        state["last_group"] = group
        state["last_requested"] = requested_isolation
        state["last_severity"] = severity
        _write_json(_STATE_PATH, state)

        if pid:
            active = _live(_load_active())
            entry = {
                "label": label,
                "group": group,
                "requested": requested_isolation,
                "severity": severity,
                "since": now,
                "pid": pid,
            }
            start = process_start_time(pid)
            if start is not None:
                entry["start"] = start
            active[f"{label}::{group}"] = entry
            _write_json(_ACTIVE_PATH, active)
    except OSError as exc:
        log.warning("could not record the fallback of %s %s: %s", label, group, exc)


def clear_fallbacks(label: str, groups: list):
    """
    Forget the active fallbacks of these groups of label: they were just
    allocated as asked (a running VM re-pinned with free cores, for one).
    """
    try:
        active = _load_active()
        live = _live(active)
        for group in groups:
            live.pop(f"{label}::{group}", None)
        if live != active:
            _write_json(_ACTIVE_PATH, live)
    except OSError as exc:
        log.warning("could not update the active fallbacks of %s: %s", label, exc)


# ---------------------------------------------------------------------------
# Prometheus text format helpers
# ---------------------------------------------------------------------------

def _escape(value) -> str:
    """
    A label value as the text format wants it. Some come from free text (a
    claim label, a VM name, the comm a process gave itself), and one bad
    line makes node_exporter drop the whole file.
    """
    return (str(value).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n"))


def _metric(buf: list, name: str, help_: str, type_: str, samples: list):
    """Append one complete metric family (HELP + TYPE + samples) to buf."""
    if not samples:
        return
    buf.append(f"# HELP {name} {help_}")
    buf.append(f"# TYPE {name} {type_}")
    for labels, value in samples:
        if labels:
            lstr = "{" + ",".join(f'{k}="{_escape(v)}"'
                                  for k, v in labels.items()) + "}"
        else:
            lstr = ""
        buf.append(f"{name}{lstr} {value}")


# ---------------------------------------------------------------------------
# Per-CPU detail builders
# ---------------------------------------------------------------------------

def _build_cpu_detail(data: dict, topo: Topology) -> list:
    """
    One sample per online CPU with full context:
    topology (isolated, ht_pair, ht_sibling) + occupancy (state, actor,
    thread group, scheduler, priority).

    state values: free | vm | irq | quadlet | run | claim | reserved | housekeeping
    """
    isolated = set(topo.isolated_cpus())

    # HT pair index (sorted by lowest CPU in pair) + sibling map
    pairs = sorted(topo.sibling_pairs(), key=min)
    pair_idx: dict = {}
    sibling_map: dict = {}
    for i, pair in enumerate(pairs):
        pair_sorted = sorted(pair)
        for cpu in pair_sorted:
            pair_idx[cpu] = i
            others = [c for c in pair_sorted if c != cpu]
            sibling_map[cpu] = others[0] if others else cpu

    # Build occupancy map: cpu_int -> info_dict
    cpu_occ: dict = {}

    # Reserved siblings are idle HT partners of exclusive_physical allocations.
    # They are blocked but have no actor entry — mark them explicitly so they
    # don't appear as "free".
    for idle_cpu, active_cpu in data.get("reserved_siblings", []):
        cpu_occ[idle_cpu] = {
            "state": "reserved",
            "label": str(active_cpu),
            "group": "ht_sibling",
            "scheduler": "",
            "priority": "0",
        }

    for actor in data["actors"]:
        t = actor["type"]
        label = actor["label"]
        if t == "vm":
            for thread in actor.get("threads", []):
                for cpu in parse_cpu_list(thread["cpus"]):
                    cpu_occ[cpu] = {
                        "state": "vm",
                        "label": label,
                        "group": thread["comm"],
                        "scheduler": thread.get("scheduler", ""),
                        "priority": str(thread.get("priority", 0)),
                    }
        elif t == "irq":
            for cpu in parse_cpu_list(actor["cpus"]):
                cpu_occ[cpu] = {
                    "state": "irq",
                    "label": label,
                    "group": "irq",
                    "scheduler": "",
                    "priority": "0",
                }
        else:
            for cpu in parse_cpu_list(actor["cpus"]):
                cpu_occ[cpu] = {
                    "state": t,
                    "label": label,
                    "group": t,
                    "scheduler": actor.get("scheduler", ""),
                    "priority": str(actor.get("priority", 0)),
                }

    samples = []
    for cpu in topo.online_cpus():
        is_isolated = cpu in isolated
        occ = cpu_occ.get(cpu)
        if occ:
            state = occ["state"]
        elif is_isolated:
            state = "free"
        else:
            state = "housekeeping"
        samples.append(({
            "cpu":       str(cpu),
            "isolated":  "1" if is_isolated else "0",
            "ht_pair":   str(pair_idx.get(cpu, 0)),
            "ht_sibling": str(sibling_map.get(cpu, cpu)),
            "state":     state,
            "label":     occ["label"]     if occ else "",
            "group":     occ["group"]     if occ else "",
            "scheduler": occ["scheduler"] if occ else "",
            "priority":  occ["priority"]  if occ else "0",
        }, 1))
    return samples


def _build_vm_thread_info(data: dict) -> list:
    """
    One sample per QEMU thread with vm, comm, tid, cpu, scheduler, priority.
    The tid keeps the series apart: the vhost workers of a VM share a comm,
    and often a core and a policy.
    """
    samples = []
    for actor in data["actors"]:
        if actor["type"] != "vm":
            continue
        for thread in actor.get("threads", []):
            samples.append(({
                "vm":        actor["label"],
                "thread":    thread["comm"],
                "tid":       str(thread.get("tid", "")),
                "cpu":       thread["cpus"],
                "scheduler": thread.get("scheduler", ""),
                "priority":  str(thread.get("priority", 0)),
            }, 1))
    return samples


def _build_irq_info(data: dict) -> list:
    """One sample per NIC/IRQ-group with iface, irq_range, cpu."""
    return [
        ({
            "iface":     actor.get("iface", ""),
            "irq_range": actor.get("irqs", ""),
            "cpu":       actor["cpus"],
        }, 1)
        for actor in data["actors"] if actor["type"] == "irq"
    ]


def _build_claim_info(data: dict) -> list:
    """One sample per active claim (quadlet, run, or generic) with label, kind,
    cpu, scheduler, priority, pid."""
    return [
        ({
            "kind":      actor["type"],
            "label":     actor["label"],
            "cpu":       actor["cpus"],
            "scheduler": actor.get("scheduler", ""),
            "priority":  str(actor.get("priority", 0)),
            "pid":       str(actor.get("pid", "")),
        }, 1)
        for actor in data["actors"] if actor["type"] not in ("vm", "irq")
    ]


def _occupied_cpu_counts(data: dict) -> list:
    """Number of occupied isolated CPUs per actor type.

    A CPU counts once per type however many threads share it, and only if it
    is isolated: a hard fallback leaves its actor on the housekeeping cores.
    """
    isolated = set(parse_cpu_list(data.get("isolated", "")))
    cpus: dict = {}
    for actor in data["actors"]:
        if actor["type"] == "vm":
            lists = [th["cpus"] for th in actor.get("threads", [])]
        else:
            lists = [actor.get("cpus", "")]
        held = cpus.setdefault(actor["type"], set())
        for cpu_list in lists:
            held.update(c for c in parse_cpu_list(cpu_list) if c in isolated)
    return [({'type': t}, len(c)) for t, c in sorted(cpus.items())]


# ---------------------------------------------------------------------------
# Main generate / write
# ---------------------------------------------------------------------------

def generate() -> str:
    data = collect()
    state = _load_state()
    topo = Topology()
    now = int(time.time())
    buf = []

    # --- Summary gauges -------------------------------------------------------
    _metric(buf,
            "seapath_alloc_isolated_cpus",
            "Total number of isolated CPUs on this node.",
            "gauge",
            [({}, len(topo.isolated_cpus()))])

    _metric(buf,
            "seapath_alloc_free_logical_cpus",
            "Free isolated logical cores available for allocation.",
            "gauge",
            [({}, len(parse_cpu_list(data["free_logical"])) if data["free_logical"] else 0)])

    _metric(buf,
            "seapath_alloc_free_physical_pairs",
            "Free isolated physical core pairs (both HT siblings available).",
            "gauge",
            [({}, len(parse_cpu_list(data["free_physical"])) if data["free_physical"] else 0)])

    type_counts: dict = {}
    for actor in data["actors"]:
        t = actor["type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    _metric(buf,
            "seapath_alloc_actors",
            "Number of active actors currently holding isolated cores, by type.",
            "gauge",
            [({'type': t}, c) for t, c in sorted(type_counts.items())])

    _metric(buf,
            "seapath_alloc_occupied_cpus",
            "Number of isolated CPUs currently occupied, by actor type.",
            "gauge",
            _occupied_cpu_counts(data))

    _metric(buf,
            "seapath_alloc_vm_threads",
            "Number of isolated-core threads currently pinned for each VM.",
            "gauge",
            [({"vm": a["label"]}, len(a.get("threads", [])))
             for a in data["actors"] if a["type"] == "vm"])

    # --- Detailed per-CPU / per-actor metrics ---------------------------------
    _metric(buf,
            "seapath_alloc_cpu_detail",
            "Per-CPU detail: topology (isolated, ht_pair, ht_sibling) and"
            " current occupancy (state, actor label, thread group,"
            " scheduler, priority)."
            " state: free|vm|irq|quadlet|run|claim|reserved|housekeeping."
            " reserved=idle HT sibling of an exclusive_physical allocation"
            " (label=active sibling CPU).",
            "gauge",
            _build_cpu_detail(data, topo))

    _metric(buf,
            "seapath_alloc_vm_thread_info",
            "Per-thread detail for each QEMU thread pinned on isolated cores."
            " thread=kernel comm, cpu=logical CPU(s), scheduler/priority as set by chrt.",
            "gauge",
            _build_vm_thread_info(data))

    _metric(buf,
            "seapath_alloc_irq_info",
            "NIC MSI-IRQ affinity: one series per interface/IRQ-group pinned"
            " on isolated cores. irq_range uses Linux cpu-list notation.",
            "gauge",
            _build_irq_info(data))

    _metric(buf,
            "seapath_alloc_claim_info",
            "Active claim detail for containers and seapath-run processes.",
            "gauge",
            _build_claim_info(data))

    # --- Active degraded actors -----------------------------------------------
    # Entries of exited processes are filtered out here and pruned by the
    # allocation pipeline, which writes the file under the pool flock: a
    # write from here would race it.
    live_active = _live(_load_active())

    sev_counts: dict = {"hard": 0, "soft": 0}
    for e in live_active.values():
        sev_counts[e["severity"]] = sev_counts.get(e["severity"], 0) + 1
    _metric(buf,
            "seapath_alloc_active_fallbacks",
            "Actors currently running in a degraded state."
            " severity=hard: no RT isolation (housekeeping)."
            " severity=soft: RT isolation preserved, HT-pair guarantee lost.",
            "gauge",
            [({'severity': sev}, cnt) for sev, cnt in sorted(sev_counts.items())])

    _metric(buf,
            "seapath_alloc_active_fallback_info",
            "One series per currently degraded actor."
            " severity=hard|soft, requested=isolation level that was asked.",
            "gauge",
            [({
                "label":     e["label"],
                "group":     e["group"],
                "requested": e["requested"],
                "severity":  e["severity"],
            }, 1) for e in live_active.values()])

    # --- Fallback counter + context -------------------------------------------
    _metric(buf,
            "seapath_alloc_allocation_fallbacks_total",
            "Total degradation events since last counter reset"
            " (hard + soft, survives reboots).",
            "counter",
            [({}, state.get("total", 0))])

    if state.get("last_ts", 0) > 0:
        _metric(buf,
                "seapath_alloc_last_fallback_timestamp_seconds",
                "Unix timestamp of the most recent degradation event.",
                "gauge",
                [({}, state["last_ts"])])
        _metric(buf,
                "seapath_alloc_last_fallback_info",
                "Context of the most recent degradation event."
                " severity=hard|soft, requested=isolation level that was asked.",
                "gauge",
                [({
                    "label":     state.get("last_label", ""),
                    "group":     state.get("last_group", ""),
                    "requested": state.get("last_requested", ""),
                    "severity":  state.get("last_severity", "hard"),
                }, 1)])

    _metric(buf,
            "seapath_alloc_scrape_timestamp_seconds",
            "Unix timestamp when seapath-alloc last wrote this metrics file.",
            "gauge",
            [({}, now)])

    return "\n".join(buf) + "\n"


def write_prom(path: str = _PROM_PATH):
    """Write current pool state as Prometheus text format, atomically."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = generate()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)
    log.debug("wrote %s", path)
