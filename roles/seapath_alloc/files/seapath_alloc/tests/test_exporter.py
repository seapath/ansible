# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the per-CPU detail builder (exporter.py).

cpu_detail has one series per CPU, so a colocated (slot) core cannot be
represented by a single actor: it must surface as state=slot with the member
list summarised in the `members` label.
"""

from seapath_alloc.exporter import _build_cpu_detail


def _sample_for(samples, cpu):
    return next(labels for labels, _ in samples if labels["cpu"] == str(cpu))


def _data(actors=None, slots=None):
    return {
        "reserved_siblings": [],
        "actors": actors or [],
        "slots": slots or [],
    }


def test_slot_core_shows_all_members(std_topology):
    data = _data(
        actors=[{
            "type": "vm", "label": "vm1",
            "threads": [
                {"comm": "qemu-system-x86_64", "cpus": "4",
                 "scheduler": "OTHER", "priority": 0},
                {"comm": "vhost-1000", "cpus": "4",
                 "scheduler": "FIFO", "priority": 3},
            ],
        }],
        slots=[{
            "name": "sv0", "cores": "4", "isolation": "exclusive_logical",
            "members": [
                {"kind": "vm", "label": "vm1", "group": "qemu-system-x86_64",
                 "scheduler": "OTHER", "priority": 0, "cpus": "4"},
                {"kind": "vm", "label": "vm1", "group": "vhost-1000",
                 "scheduler": "FIFO", "priority": 3, "cpus": "4"},
            ],
            "warnings": [],
        }],
    )
    s = _sample_for(_build_cpu_detail(data, std_topology), 4)
    assert s["state"] == "slot"
    assert s["slot"] == "sv0"
    assert s["label"] == "sv0"
    assert s["member_count"] == "2"
    assert "vm1/qemu-system-x86_64 OTHER/0" in s["members"]
    assert "vm1/vhost-1000 FIFO/3" in s["members"]


def test_memberless_slot_core(std_topology):
    data = _data(slots=[{
        "name": "sv0", "cores": "6", "isolation": "exclusive_logical",
        "members": [], "warnings": [],
    }])
    s = _sample_for(_build_cpu_detail(data, std_topology), 6)
    assert s["state"] == "slot"
    assert s["member_count"] == "0"
    assert s["members"] == ""


def test_non_slot_cores_unchanged(std_topology):
    data = _data(actors=[{
        "type": "vm", "label": "vm1",
        "threads": [{"comm": "CPU 0/KVM", "cpus": "8",
                     "scheduler": "FIFO", "priority": 90}],
    }])
    samples = _build_cpu_detail(data, std_topology)
    vm = _sample_for(samples, 8)
    assert vm["state"] == "vm"
    assert vm["label"] == "vm1"
    assert vm["slot"] == ""
    assert vm["members"] == ""
    assert _sample_for(samples, 4)["state"] == "free"
    assert _sample_for(samples, 0)["state"] == "housekeeping"


def test_slot_with_irq_member_is_irq_slot(std_topology):
    data = _data(slots=[{
        "name": "sv0", "cores": "6", "isolation": "exclusive_logical",
        "members": [
            {"kind": "irq", "label": "eth0/10-13", "group": "irq",
             "scheduler": "", "priority": 0, "cpus": "6"},
            {"kind": "run", "label": "sv-proc", "group": "run",
             "scheduler": "FIFO", "priority": 10, "cpus": "6"},
        ],
        "warnings": [],
    }])
    s = _sample_for(_build_cpu_detail(data, std_topology), 6)
    assert s["state"] == "irq_slot"
    assert s["slot"] == "sv0"
    assert s["member_count"] == "2"
