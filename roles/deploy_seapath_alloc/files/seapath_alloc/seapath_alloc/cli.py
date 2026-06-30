# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
seapath-alloc CLI entry point.

Subcommands: status, claim, release, spread, export.
Data collection is in status.py; this module only contains argument parsing
and subcommand dispatch.
"""

import argparse
import json
import sys

from .logging_setup import setup_logging
from .status import collect
from .topology import format_cpu_list


def main():
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
    claim_p.add_argument("--target-pid", type=int, default=0, metavar="PID")
    claim_p.add_argument("--no-apply", action="store_true", default=False,
                         help="Register the claim without pinning the calling process"
                              " via taskset/chrt (use with --target-pid to set the"
                              " owning PID explicitly)")

    # release
    rel_p = sub.add_parser("release", help="Release a claim")
    rel_p.add_argument("--label", required=True)

    # spread
    spread_p = sub.add_parser(
        "spread",
        help="Move threads out of shared HT pairs into free pairs",
    )
    spread_p.add_argument(
        "--dry-run", action="store_true",
        help="Print planned moves without applying them",
    )

    # export
    sub.add_parser("export",
                   help="Write Prometheus metrics to"
                        " /var/lib/prometheus/node_exporter/seapath-alloc.prom")

    args = parser.parse_args()

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
        from .claim import claim as do_claim
        cores = do_claim(
            label=args.label,
            isolation=args.isolation,
            scheduler=args.scheduler,
            priority=args.priority,
            profile_path=args.profile,
            target_pid=args.target_pid,
            no_apply=args.no_apply,
        )
        print(format_cpu_list(cores))

    elif args.command == "release":
        from .claim import release as do_release
        do_release(args.label)

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

    elif args.command == "export":
        from .exporter import write_prom
        write_prom()

    else:
        parser.print_help()
        sys.exit(1)
