# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
CPU topology discovery from /sys/devices/system/cpu/.

Reads three things:
- which cores are isolated (removed from the Linux scheduler by isolcpus=)
- which cores are online
- which logical cores share a physical core (Hyper-Threading siblings)

The sys_cpu_path parameter lets unit tests inject a fake /sys tree.
"""

import os


def parse_cpu_list(s: str) -> list:
    """
    Parse a Linux cpu-list string into a sorted list of ints.

    Linux uses this format everywhere: isolcpus=, Cpus_allowed_list,
    smp_affinity_list, thread_siblings_list, taskset output, etc.

    Examples:
      "4"        → [4]
      "4,6"      → [4, 6]
      "4-7"      → [4, 5, 6, 7]
      "0-3,6-9"  → [0, 1, 2, 3, 6, 7, 8, 9]
    """
    result = []
    for part in s.strip().split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo, hi = part.split('-', 1)
            result.extend(range(int(lo), int(hi) + 1))
        else:
            result.append(int(part))
    return sorted(result)


def format_cpu_list(cpus) -> str:
    """
    Format a collection of ints as a Linux cpu-list string.

    Compresses consecutive runs into ranges:
      [4, 5, 6, 8] → "4-6,8"
    """
    if not cpus:
        return ""
    cpus = sorted(set(cpus))
    ranges = []
    start = prev = cpus[0]
    for c in cpus[1:]:
        if c == prev + 1:
            prev = c
        else:
            ranges.append((start, prev))
            start = prev = c
    ranges.append((start, prev))
    return ','.join(str(s) if s == e else f"{s}-{e}" for s, e in ranges)


class Topology:
    """
    CPU topology of the local node.

    All reads are lazy and cached — the topology doesn't change at runtime,
    so there's no need to re-read /sys on repeated calls.
    """

    def __init__(self, sys_cpu_path: str = "/sys/devices/system/cpu"):
        self._path = sys_cpu_path
        self._isolated = None
        self._online = None
        self._sibling_pairs = None

    def _read(self, name: str) -> str:
        try:
            with open(os.path.join(self._path, name)) as f:
                return f.read().strip()
        except OSError:
            return ""

    def isolated_cpus(self) -> list:
        """Cores removed from the Linux scheduler by the isolcpus= kernel parameter."""
        if self._isolated is None:
            raw = self._read("isolated")
            self._isolated = parse_cpu_list(raw) if raw else []
        return self._isolated

    def online_cpus(self) -> list:
        """All logical cores currently online."""
        if self._online is None:
            raw = self._read("online")
            self._online = parse_cpu_list(raw) if raw else []
        return self._online

    def housekeeping_cpus(self) -> list:
        """Cores not isolated — the scheduler's default domain."""
        isolated = set(self.isolated_cpus())
        return [c for c in self.online_cpus() if c not in isolated]

    def siblings_of(self, cpu: int) -> list:
        """All logical CPUs (including cpu itself) sharing its physical core."""
        for pair in self.sibling_pairs():
            if cpu in pair:
                return sorted(pair)
        return [cpu]

    def sibling_pairs(self) -> list:
        """
        Deduplicated list of frozensets, each containing the logical CPUs that
        share one physical core.

        On a non-HT system every frozenset has one element.
        On a 2-way HT system every frozenset has two elements.
        """
        if self._sibling_pairs is not None:
            return self._sibling_pairs

        seen = set()
        pairs = []
        for cpu in self.online_cpus():
            path = os.path.join(
                self._path, f"cpu{cpu}", "topology", "thread_siblings_list"
            )
            try:
                with open(path) as f:
                    raw = f.read().strip()
            except OSError:
                raw = str(cpu)
            group = frozenset(parse_cpu_list(raw))
            if group not in seen:
                seen.add(group)
                pairs.append(group)
        self._sibling_pairs = pairs
        return pairs

    def isolated_sibling_pairs(self) -> list:
        """Sibling pairs where every member is isolated."""
        isolated = set(self.isolated_cpus())
        return [p for p in self.sibling_pairs() if p.issubset(isolated)]
