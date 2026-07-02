# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Tests for slot member attribution and colocation warnings (status.py).

These are pure functions over the collected actor list — no /proc needed.
"""

from seapath_alloc.status import _build_slots, _slot_warnings


def _vm_actor(label, threads):
    return {"type": "vm", "label": label, "threads": threads}


def _thread(comm, cpus, scheduler="FIFO", priority=10):
    return {"comm": comm, "cpus": cpus,
            "scheduler": scheduler, "priority": priority}


def _irq_actor(iface, cpus):
    return {"type": "irq", "label": f"{iface}/10-13", "iface": iface,
            "irqs": "10-13", "cpus": cpus}


def _claim_actor(label, cpus, scheduler="FIFO", priority=10, kind="run"):
    return {"type": kind, "label": label, "pid": 1234, "cpus": cpus,
            "scheduler": scheduler, "priority": priority, "slot": ""}


SLOT = {"name": "x", "cores": [4], "isolation": "exclusive_logical",
        "created": 0}


# ------------------------------------------------------------------ members

def test_members_from_vm_irq_and_claim():
    actors = [
        _vm_actor("vm1", [_thread("qemu-system-x86_64", "4", "OTHER", 0),
                          _thread("CPU 0/KVM", "8")]),
        _irq_actor("eth0", "4"),
        _claim_actor("sv-proc", "4"),
        _claim_actor("elsewhere", "6"),
    ]
    slots = _build_slots([SLOT], actors)
    assert len(slots) == 1
    members = slots[0]["members"]
    assert [(m["kind"], m["label"]) for m in members] == [
        ("vm", "vm1"), ("irq", "eth0/10-13"), ("run", "sv-proc")]
    # The vCPU on cpu 8 is outside the slot and must not appear.
    assert all(m["group"] != "CPU 0/KVM" for m in members)


def test_empty_slot_has_no_members_and_no_warnings():
    slots = _build_slots([SLOT], [])
    assert slots[0]["members"] == []
    assert slots[0]["warnings"] == []


# ------------------------------------------------------------------ warnings

def test_equal_rt_priority_between_distinct_actors():
    members = [
        {"kind": "run", "label": "a", "group": "run",
         "scheduler": "FIFO", "priority": 10},
        {"kind": "run", "label": "b", "group": "run",
         "scheduler": "FIFO", "priority": 10},
    ]
    assert "equal_rt_priority" in _slot_warnings(members)


def test_equal_rt_priority_ignores_same_thread_group():
    """Several threads of the same group at the same priority are the norm
    (e.g. a vhost group sharing its cores) — no warning."""
    members = [
        {"kind": "vm", "label": "vm1", "group": "vhost-1000",
         "scheduler": "FIFO", "priority": 1},
        {"kind": "vm", "label": "vm1", "group": "vhost-1000",
         "scheduler": "FIFO", "priority": 1},
    ]
    assert _slot_warnings(members) == []


def test_rt_priority_ge_irq():
    members = [
        {"kind": "irq", "label": "eth0/10-13", "group": "irq",
         "scheduler": "", "priority": 0},
        {"kind": "run", "label": "hungry", "group": "run",
         "scheduler": "FIFO", "priority": 50},
    ]
    assert "rt_priority_ge_irq" in _slot_warnings(members)


def test_rt_priority_below_irq_is_fine():
    members = [
        {"kind": "irq", "label": "eth0/10-13", "group": "irq",
         "scheduler": "", "priority": 0},
        {"kind": "run", "label": "polite", "group": "run",
         "scheduler": "FIFO", "priority": 10},
    ]
    assert _slot_warnings(members) == []


def test_vcpu_shared_with_other_actor():
    members = [
        {"kind": "vm", "label": "vm1", "group": "CPU 0/KVM",
         "scheduler": "FIFO", "priority": 90},
        {"kind": "run", "label": "proc", "group": "run",
         "scheduler": "FIFO", "priority": 10},
    ]
    assert "vcpu_shared" in _slot_warnings(members)


def test_vcpu_alone_on_slot_no_warning():
    members = [
        {"kind": "vm", "label": "vm1", "group": "CPU 0/KVM",
         "scheduler": "FIFO", "priority": 90},
    ]
    assert _slot_warnings(members) == []
