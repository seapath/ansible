# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Thread-migration helpers for CPU pair management.

Two complementary operations:

  find_repack_moves()  — COMPACTION: before allocating a new VM, consolidate
    half-used physical pairs (one sibling busy, one free) so that some pairs
    become fully free for exclusive_physical allocations.

  find_spread_moves()  — SPREADING: after VMs stop or when pairs are over-
    shared, move a thread out of every contended pair into a fully-free pair so
    each workload ends up alone on its physical core.  A pair is contended when
    both siblings carry a workload OR a workload shares the core with a NIC IRQ
    on its HT sibling — the IRQ generates the same HT interference a second
    workload would, so spreading treats them the same.  This is the inverse of
    compaction.

Both operations work on all seapath-alloc managed actors:
  - QEMU threads (VMs): moved via taskset per thread ID
  - seapath-run processes: moved via taskset per thread ID (children included
    because they inherit affinity at exec time and appear on the same CPU)
  - quadlet containers: moved via cgroup cpuset.cpus write + taskset per PID

Design constraints shared by both:
  - Only moves actors exclusively on a single isolated CPU.  We never touch
    threads with broad affinity or multiple allowed CPUs.
  - Slot cores are never moved: a named slot colocates several actors
    (possibly including IRQs, which taskset cannot move) on the same core,
    and moving one member would break the colocation.  Slot cores still
    count as occupied for pair accounting, and spreading treats them as
    HT interferers exactly like NIC IRQs.
  - A ThreadMove is a single taskset -cp call; it does not change the
    scheduler class or RT priority of the thread.
  - A CgroupMove writes a new cpuset.cpus to the full cgroup tree and
    calls taskset on every PID found in the cgroup.
  - The caller must bust the pool cache (pool.bust_cache()) after
    execute_repack() so that subsequent free_logical()/free_physical() calls
    see the updated /proc state.
"""

import logging
import subprocess
from dataclasses import dataclass
from typing import List, Union

log = logging.getLogger(__name__)


@dataclass
class ThreadMove:
    """Move every workload thread pinned to from_cpu to a different isolated CPU.

    tids holds all threads currently on from_cpu (a seapath-run process and its
    inherited children all share one core), so moving the core means moving them
    all to to_cpu — otherwise the donor core is never actually freed.
    """
    tids: list
    from_cpu: int
    to_cpu: int


@dataclass
class CgroupMove:
    """Move a quadlet container to a different isolated CPU via cgroup cpuset."""
    label: str
    service: str
    from_cpu: int
    to_cpu: int


RepackMove = Union[ThreadMove, CgroupMove]


def _make_move(from_cpu: int, to_cpu: int,
               cpu_to_tids: dict, cpu_to_quadlet: dict) -> RepackMove:
    if from_cpu in cpu_to_quadlet:
        label, service = cpu_to_quadlet[from_cpu]
        return CgroupMove(label=label, service=service,
                          from_cpu=from_cpu, to_cpu=to_cpu)
    return ThreadMove(tids=list(cpu_to_tids[from_cpu]),
                      from_cpu=from_cpu, to_cpu=to_cpu)


def find_repack_moves(pool, needed_pairs: int) -> List[RepackMove]:
    """
    Find moves that would free physical pairs to cover needed_pairs.

    Returns a list of RepackMove.  Applying all of them consolidates actors
    so that `needed_pairs` additional physical pairs become fully free.

    The algorithm:
      1. Build a map: physical_lower → [CPUs in that pair occupied by an actor].
      2. Find "donor" pairs: pairs with exactly one occupied actor sibling.
      3. Find "receiver" pairs: any isolated pair with at least one free landing
         slot.  Donor pairs qualify — moving an actor FROM donor pair A TO the
         free sibling of donor pair B frees pair A entirely.
      4. For each shortfall pair needed: pick a donor and a different receiver
         pair, schedule the actor to move to the receiver's free slot.
    """
    topo = pool._topo
    isolated = set(topo.isolated_cpus())
    free_l = set(pool.free_logical())
    slot_cores = pool.slot_cores()

    # Slot cores are unmoveable (colocation) but still occupy their pair.
    cpu_to_tids: dict = {
        c: t for c, t in pool.pinned_workload_threads().items()
        if c not in slot_cores
    }
    cpu_to_quadlet: dict = {
        c: q for c, q in pool.pinned_quadlet_cpus().items()
        if c not in slot_cores
    }
    occupied_cpus = (set(cpu_to_tids.keys()) | set(cpu_to_quadlet.keys())
                     | (slot_cores & isolated))

    pair_occupied: dict = {}
    for cpu in isolated:
        lower = min(topo.siblings_of(cpu))
        pair_occupied.setdefault(lower, set())
        if cpu in occupied_cpus:
            pair_occupied[lower].add(cpu)

    donors = []
    for lower, occupied in pair_occupied.items():
        siblings = set(topo.siblings_of(lower))
        free_in_pair = (siblings & free_l) - occupied_cpus
        if len(occupied) == 1 and free_in_pair:
            from_cpu = next(iter(occupied))
            if from_cpu in slot_cores:
                continue
            donors.append((lower, from_cpu))

    receivers = []
    for lower, occupied in pair_occupied.items():
        siblings = set(topo.siblings_of(lower))
        free_in_pair = (siblings & free_l) - occupied_cpus
        for free_slot in sorted(free_in_pair):
            receivers.append((lower, free_slot))

    moves: List[RepackMove] = []
    # Track whole pairs, not raw slots: once a pair has donated its occupant it
    # becomes free, and once it has received one it becomes occupied — either
    # way it must not be picked again, including as the other role. Keying on
    # the slot let a pair that just received a thread be re-used as a donor,
    # which left the received slot occupied and the "freed" pair still half-full.
    used_donor_pairs: set = set()
    used_receiver_pairs: set = set()

    for _ in range(needed_pairs):
        donor = next(
            (d for d in donors
             if d[0] not in used_donor_pairs and d[0] not in used_receiver_pairs),
            None,
        )
        if donor is None:
            log.debug("repacker: no more donors available after %d moves", len(moves))
            break

        lower_d, from_cpu = donor

        recv = next(
            (r for r in receivers
             if r[0] not in used_donor_pairs
             and r[0] not in used_receiver_pairs
             and r[0] != lower_d),
            None,
        )
        if recv is None:
            log.debug("repacker: no receiver available for donor pair %d", lower_d)
            break

        lower_r, to_cpu = recv

        moves.append(_make_move(from_cpu, to_cpu, cpu_to_tids, cpu_to_quadlet))
        used_donor_pairs.add(lower_d)
        used_receiver_pairs.add(lower_r)

    return moves


def find_spread_moves(pool) -> List[RepackMove]:
    """
    Find moves that give every workload an uncontended physical core.

    Returns a list of RepackMove.  Applying them moves a thread out of every
    contended pair into a fully-free pair, so each workload ends up alone on
    its physical core — mirroring what the SPREADING allocator does at
    allocation time (it places a logical thread on a clean pair rather than
    next to a NIC IRQ).

    A pair is contended when:
      - both HT siblings carry a workload (move the upper sibling's thread,
        keeping the lower/T0 in place), or
      - a single workload shares the core with a NIC IRQ on its HT sibling
        (move that workload).

    Reserved HT siblings of exclusive_physical allocations are NOT interferers
    (the idle sibling is parked on purpose), and receivers are restricted to
    fully-free pairs (pool.free_physical()), so an exclusive_physical thread is
    never disturbed and a thread never lands next to an IRQ or a reservation.
    """
    topo = pool._topo
    isolated = set(topo.isolated_cpus())
    slot_cores = pool.slot_cores()

    # Slot cores are unmoveable (colocation); as HT-sibling neighbours they
    # interfere like a NIC IRQ would, so treat them as interferers below.
    cpu_to_tids: dict = {
        c: t for c, t in pool.pinned_workload_threads().items()
        if c not in slot_cores
    }
    cpu_to_quadlet: dict = {
        c: q for c, q in pool.pinned_quadlet_cpus().items()
        if c not in slot_cores
    }
    workload_cpus = set(cpu_to_tids.keys()) | set(cpu_to_quadlet.keys())
    interferer_cpus = pool._busy_by_irqs(isolated) | (slot_cores & isolated)

    pair_workload: dict = {}
    for cpu in isolated:
        lower = min(topo.siblings_of(cpu))
        pair_workload.setdefault(lower, set())
        if cpu in workload_cpus:
            pair_workload[lower].add(cpu)

    # One workload thread to evacuate per contended pair.
    sources = []
    for lower in sorted(pair_workload):
        wl = pair_workload[lower]
        siblings = set(topo.siblings_of(lower))
        if len(wl) == 2:
            # Dense: move the upper sibling's thread, keep the lower (T0).
            sources.append(max(wl))
        elif len(wl) == 1 and (siblings & interferer_cpus):
            # Workload sharing its physical core with a NIC IRQ or a slot.
            sources.append(next(iter(wl)))

    # Landing zones: fully-free pairs only (no workload, no IRQ, no reservation).
    receivers = list(pool.free_physical())

    moves: List[RepackMove] = []
    used_receivers: set = set()
    for from_cpu in sources:
        recv = next((r for r in receivers if r not in used_receivers), None)
        if recv is None:
            log.debug("spreader: no free pair for contended cpu %d", from_cpu)
            break
        moves.append(_make_move(from_cpu, recv, cpu_to_tids, cpu_to_quadlet))
        used_receivers.add(recv)

    return moves


def execute_repack(moves: List[RepackMove], taskset_bin: str = "taskset",
                   pool=None) -> None:
    """Apply a list of repack moves.

    pool must be provided when moves may include CgroupMove entries — it is
    used to update claims.json so the pool state stays consistent after the
    cgroup/taskset migration.
    """
    for move in moves:
        if isinstance(move, ThreadMove):
            for tid in move.tids:
                cmd = [taskset_bin, "-cp", str(move.to_cpu), str(tid)]
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if r.returncode != 0:
                        log.warning("repacker: taskset failed for tid %d (%d→%d): %s",
                                    tid, move.from_cpu, move.to_cpu, r.stderr.strip())
                    else:
                        log.info("repacker: moved tid %d cpu %d → cpu %d",
                                 tid, move.from_cpu, move.to_cpu)
                except (subprocess.TimeoutExpired, OSError) as exc:
                    log.warning("repacker: taskset error for tid %d: %s", tid, exc)

        elif isinstance(move, CgroupMove):
            from .cgroup import apply_cpuset, cgroup_procs, cgroup_root, taskset_procs
            cpu_str = str(move.to_cpu)
            root = cgroup_root(move.service)
            if root is None:
                log.warning("repacker: cgroup not found for %s", move.service)
                continue
            apply_cpuset(root, cpu_str)
            pids = cgroup_procs(root)
            taskset_procs(pids, cpu_str)
            if pool is not None:
                pool.move_claim_cpu(move.label, move.to_cpu)
            log.info("repacker: moved quadlet %r cpu %d → cpu %d",
                     move.label, move.from_cpu, move.to_cpu)
