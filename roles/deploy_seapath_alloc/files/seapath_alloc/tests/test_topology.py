# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import pytest
from seapath_alloc.topology import parse_cpu_list, format_cpu_list, Topology
from tests.conftest import make_cpu_topology


# ------------------------------------------------------------------ parse_cpu_list

def test_parse_single():
    assert parse_cpu_list("4") == [4]

def test_parse_comma():
    assert parse_cpu_list("4,6,8") == [4, 6, 8]

def test_parse_range():
    assert parse_cpu_list("4-7") == [4, 5, 6, 7]

def test_parse_mixed():
    assert parse_cpu_list("0-3,6,8-9") == [0, 1, 2, 3, 6, 8, 9]

def test_parse_empty():
    assert parse_cpu_list("") == []

def test_parse_whitespace():
    assert parse_cpu_list("  4-5 , 8 ") == [4, 5, 8]

def test_parse_sorted():
    assert parse_cpu_list("8,4,6") == [4, 6, 8]


# ------------------------------------------------------------------ format_cpu_list

def test_format_empty():
    assert format_cpu_list([]) == ""

def test_format_single():
    assert format_cpu_list([4]) == "4"

def test_format_no_range():
    assert format_cpu_list([4, 6, 8]) == "4,6,8"

def test_format_range():
    assert format_cpu_list([4, 5, 6, 7]) == "4-7"

def test_format_mixed():
    assert format_cpu_list([0, 1, 2, 3, 6, 8, 9]) == "0-3,6,8-9"

def test_format_deduplicates():
    assert format_cpu_list([4, 4, 5]) == "4-5"

def test_roundtrip(std_topology):
    cpus = std_topology.isolated_cpus()
    assert parse_cpu_list(format_cpu_list(cpus)) == cpus


# ------------------------------------------------------------------ Topology

def test_isolated(std_topology):
    assert std_topology.isolated_cpus() == [4, 5, 6, 7, 8, 9, 10, 11]

def test_online(std_topology):
    assert std_topology.online_cpus() == list(range(12))

def test_housekeeping(std_topology):
    assert std_topology.housekeeping_cpus() == [0, 1, 2, 3]

def test_sibling_pairs_count(std_topology):
    assert len(std_topology.sibling_pairs()) == 6

def test_sibling_pairs_content(std_topology):
    pairs = std_topology.sibling_pairs()
    assert frozenset({4, 5}) in pairs
    assert frozenset({8, 9}) in pairs

def test_siblings_of(std_topology):
    assert std_topology.siblings_of(4) == [4, 5]
    assert std_topology.siblings_of(5) == [4, 5]
    assert std_topology.siblings_of(10) == [10, 11]

def test_siblings_of_housekeeping(std_topology):
    assert std_topology.siblings_of(0) == [0, 1]

def test_isolated_sibling_pairs(std_topology):
    ipairs = std_topology.isolated_sibling_pairs()
    assert len(ipairs) == 4  # (4,5), (6,7), (8,9), (10,11)
    assert frozenset({4, 5}) in ipairs
    assert frozenset({0, 1}) not in ipairs

def test_no_isolated(tmp_path):
    sys_path = make_cpu_topology(tmp_path, online="0-3", isolated="")
    topo = Topology(sys_cpu_path=sys_path)
    assert topo.isolated_cpus() == []
    assert topo.housekeeping_cpus() == [0, 1, 2, 3]

def test_all_isolated(tmp_path):
    sys_path = make_cpu_topology(tmp_path, online="0-3", isolated="0-3",
                                  pairs=[(0, 1), (2, 3)])
    topo = Topology(sys_cpu_path=sys_path)
    assert topo.housekeeping_cpus() == []
    assert len(topo.isolated_sibling_pairs()) == 2
