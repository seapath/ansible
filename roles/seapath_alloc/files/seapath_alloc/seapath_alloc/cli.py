# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
seapath-alloc CLI entry point.

Subcommands: status, claim, release, spread.
Data collection is in status.py; this module only contains argument parsing
and subcommand dispatch.
"""

import argparse
import json
import sys

from .logging_setup import setup_logging
from .status import collect
from .topology import format_cpu_list


def main(argv=None):
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Show live CPU allocation state on this SEAPATH node"
    )
    sub = parser.add_subparsers(dest="command")

    # status
    status_p = sub.add_parser("status", help="Show allocation state")
    status_p.add_argument("--json", action="store_true")

    # claim
    claim_p = sub.add_parser("claim", help="Claim isolated cores")
    claim_p.add_argument("--label", required=True)
    claim_p.add_argument("--isolation", default="exclusive_logical")
    claim_p.add_argument("--scheduler", default="OTHER")
    claim_p.add_argument("--priority", type=int, default=0)
    claim_p.add_argument("--profile", default="", metavar="FILE")
    # Required: this command exits at once, and its parent is sudo when it
    # is run through sudo, so no default owner outlives it reliably.
    claim_p.add_argument("--target-pid", type=int, required=True, metavar="PID",
                         help="Process owning the claim, pinned and scheduled"
                              " unless --no-apply; the claim lapses with it."
                              " From a shell that then execs the workload,"
                              " pass $$")
    claim_p.add_argument("--no-apply", action="store_true", default=False,
                         help="Register the claim without pinning the target"
                              " process via taskset/chrt")

    # release
    rel_p = sub.add_parser("release", help="Release a claim")
    rel_p.add_argument("--label", required=True)
    rel_p.add_argument("--force", action="store_true", default=False,
                       help="Release a claim whose owner is still running;"
                            " the owner keeps its cores but no longer"
                            " holds the label")

    # spread
    spread_p = sub.add_parser(
        "spread",
        help="Move threads out of shared HT pairs into free pairs",
    )
    spread_p.add_argument(
        "--dry-run", action="store_true",
        help="Print planned moves without applying them",
    )

    args = parser.parse_args(argv)

    if args.command == "status" or args.command is None:
        data = collect()
        if getattr(args, 'json', False):
            print(json.dumps(data, indent=2))
        else:
            print(f"Isolated: {data['isolated']}")
            print(f"Free logical: {data['free_logical']}")
            print(f"Free physical pairs: {data['free_physical']}")
            if data['actors']:
                print("\nActive actors:")
                for actor in data['actors']:
                    t = actor['type']
                    if t == 'vm':
                        print(f"  VM {actor['label']}:")
                        for th in actor.get('threads', []):
                            sched = th.get('scheduler', '')
                            prio = th.get('priority', 0)
                            sched_str = f"  {sched}/{prio}" if sched else ""
                            print(f"    {th['comm']:20s}  cpus={th['cpus']}{sched_str}")
                    elif t == 'irq':
                        print(f"  IRQ {actor['label']:20s}  cpus={actor['cpus']}")
                    else:
                        sched = actor.get('scheduler', '')
                        prio = actor.get('priority', 0)
                        sched_str = f"  {sched}/{prio}" if sched else ""
                        print(f"  {t:7s} {actor['label']:18s}  cpus={actor['cpus']}  pid={actor.get('pid')}{sched_str}")

    elif args.command == "claim":
        from .allocator import HARD
        from .claim import ClaimError, claim_allocation, release as do_release
        try:
            alloc = claim_allocation(
                label=args.label,
                isolation=args.isolation,
                scheduler=args.scheduler,
                priority=args.priority,
                profile_path=args.profile,
                target_pid=args.target_pid,
                no_apply=args.no_apply,
            )
        except ClaimError as exc:
            print(f"seapath-alloc claim: {exc}", file=sys.stderr)
            sys.exit(1)
        if alloc.severity == HARD and args.scheduler.upper() in ("FIFO", "RR"):
            # As seapath-run: the workload would run as OTHER on the
            # housekeeping cores while its operator believes it is real time.
            do_release(args.label, pid=args.target_pid)
            print(f"seapath-alloc claim: no isolated core for {args.label!r}"
                  f" ({alloc.warning}), not claimed", file=sys.stderr)
            sys.exit(1)
        if alloc.warning:
            print(f"seapath-alloc claim: warning: {alloc.warning}",
                  file=sys.stderr)
        print(format_cpu_list(alloc.cpus))

    elif args.command == "release":
        from .claim import release as do_release
        from .pool import CorePool
        with CorePool() as pool:
            owners = [c.get("pid") for c in pool.all_claims()
                      if c.get("label") == args.label]
        if not owners:
            print(f"seapath-alloc release: no claim {args.label!r}",
                  file=sys.stderr)
            sys.exit(1)
        # all_claims() lists only the claims whose owner is alive, or that
        # have none.
        live = [pid for pid in owners if pid]
        if live and not args.force:
            print(f"seapath-alloc release: {args.label!r} is held by live pid"
                  f" {live[0]}; stop it, or pass --force", file=sys.stderr)
            sys.exit(1)
        if not do_release(args.label):
            print(f"seapath-alloc release: no claim {args.label!r}",
                  file=sys.stderr)
            sys.exit(1)

    elif args.command == "spread":
        from .pool import CorePool
        from .repacker import ThreadMove, execute_repack, find_spread_moves
        from .topology import Topology as _Topo

        def _fmt(move):
            if isinstance(move, ThreadMove):
                tids = ",".join(str(t) for t in move.tids)
                return f"  tids {tids:<12s}  cpu{move.from_cpu} → cpu{move.to_cpu}"
            return f"  {move.label:22s}  cpu{move.from_cpu} → cpu{move.to_cpu}"

        topo = _Topo()
        with CorePool(topology=topo) as pool:
            moves = find_spread_moves(pool)
            if not moves:
                print("Spread: nothing to do — no workload shares a physical core"
                      " with another workload or a NIC IRQ.")
            elif args.dry_run:
                print(f"Spread: {len(moves)} move(s) planned (dry-run, not applied).")
                for move in moves:
                    print(_fmt(move))
            else:
                execute_repack(moves, pool=pool)
                pool.bust_cache()
                print(f"Spread: applied {len(moves)} move(s).")
                for move in moves:
                    print(_fmt(move))

    else:
        parser.print_help()
        sys.exit(1)
