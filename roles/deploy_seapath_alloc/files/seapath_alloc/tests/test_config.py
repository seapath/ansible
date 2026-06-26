# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import pytest
from seapath_alloc.config import (
    normalize_profile,
    expand_group_specs,
    _vcpu_count_from_xml,
    _rbd_source_from_xml,
)


# ------------------------------------------------------------------ normalize_profile

def test_normalize_empty_is_all_none():
    p = normalize_profile({})
    assert p["vcpus"]["isolation"] == "none"
    assert p["emulator"]["isolation"] == "none"


def test_normalize_partial_vcpus():
    p = normalize_profile({"vcpus": {"isolation": "exclusive_physical"}})
    assert p["vcpus"]["isolation"] == "exclusive_physical"
    assert p["vcpus"]["scheduler"] == "FIFO"   # isolation → FIFO inferred
    assert p["vcpus"]["priority"] == 1          # FIFO without explicit priority → 1


def test_normalize_isolation_infers_fifo():
    """Non-none isolation without a scheduler implies RT intent → FIFO/1."""
    for level in ("exclusive_logical", "exclusive_physical"):
        p = normalize_profile({"emulator": {"isolation": level}})
        assert p["emulator"]["scheduler"] == "FIFO", level
        assert p["emulator"]["priority"] == 1, level


def test_normalize_isolation_with_explicit_other():
    """Explicit scheduler overrides the isolation-driven FIFO inference."""
    p = normalize_profile({"vcpus": {"isolation": "exclusive_physical",
                                      "scheduler": "OTHER"}})
    assert p["vcpus"]["scheduler"] == "OTHER"
    assert p["vcpus"]["priority"] == 0


def test_normalize_fifo_without_priority_defaults_to_1():
    p = normalize_profile({"vhost": {"scheduler": "FIFO"}})
    assert p["vhost"]["scheduler"] == "FIFO"
    assert p["vhost"]["priority"] == 1


def test_normalize_rr_without_priority_defaults_to_1():
    p = normalize_profile({"vhost": {"scheduler": "RR"}})
    assert p["vhost"]["priority"] == 1


def test_normalize_explicit_priority_wins():
    """An explicit priority value is never overridden by inference."""
    p = normalize_profile({"vcpus": {"isolation": "exclusive_physical",
                                      "priority": 90}})
    assert p["vcpus"]["scheduler"] == "FIFO"
    assert p["vcpus"]["priority"] == 90

    p2 = normalize_profile({"emulator": {"scheduler": "FIFO", "priority": 50}})
    assert p2["emulator"]["priority"] == 50


def test_normalize_vcpus_list():
    raw = {"vcpus": [
        {"isolation": "exclusive_physical", "scheduler": "FIFO", "priority": 90},
        {"isolation": "none"},
    ]}
    p = normalize_profile(raw)
    assert isinstance(p["vcpus"], list)
    assert p["vcpus"][0]["isolation"] == "exclusive_physical"
    assert p["vcpus"][1]["isolation"] == "none"
    assert p["vcpus"][1]["scheduler"] == "OTHER"   # none isolation → OTHER


def test_normalize_other_scheduler_forces_priority_zero():
    """Priority is meaningless for OTHER/BATCH — normalize silently drops it."""
    p = normalize_profile({"vcpus": {"isolation": "none", "scheduler": "OTHER",
                                      "priority": 99}})
    assert p["vcpus"]["priority"] == 0


def test_normalize_batch_scheduler_forces_priority_zero():
    p = normalize_profile({"emulator": {"scheduler": "BATCH", "priority": 50}})
    assert p["emulator"]["priority"] == 0


def test_normalize_vcpus_empty_list_gets_default():
    p = normalize_profile({"vcpus": []})
    assert isinstance(p["vcpus"], list)
    assert len(p["vcpus"]) == 1
    assert p["vcpus"][0]["isolation"] == "none"


# ------------------------------------------------------------------ expand_group_specs

def _make_profile(vcpus_spec, emulator=None, vhost=None, iothread=None):
    raw = {"vcpus": vcpus_spec}
    if emulator:
        raw["emulator"] = emulator
    if vhost:
        raw["vhost"] = vhost
    if iothread:
        raw["iothread"] = iothread
    return normalize_profile(raw)


def test_expand_uniform_vcpus():
    p = _make_profile({"isolation": "exclusive_logical", "scheduler": "FIFO",
                        "priority": 80})
    specs = expand_group_specs(p, vcpu_count=3, vhost_count=0, iothread_count=0)
    vcpu_specs = [s for s in specs if s["name"].startswith("vcpu")]
    assert len(vcpu_specs) == 3
    assert all(s["isolation"] == "exclusive_logical" for s in vcpu_specs)
    assert all(s["scheduler"] == "FIFO" for s in vcpu_specs)


def test_expand_list_vcpus_exact():
    p = _make_profile([
        {"isolation": "exclusive_physical", "scheduler": "FIFO", "priority": 90},
        {"isolation": "none", "scheduler": "OTHER", "priority": 0},
    ])
    specs = expand_group_specs(p, vcpu_count=2, vhost_count=0, iothread_count=0)
    vcpu_specs = [s for s in specs if s["name"].startswith("vcpu")]
    assert vcpu_specs[0]["isolation"] == "exclusive_physical"
    assert vcpu_specs[1]["isolation"] == "none"


def test_expand_list_vcpus_shorter_repeats_last():
    """With 4 vCPUs and a 2-entry list, vCPUs 2 and 3 inherit entry 1."""
    p = _make_profile([
        {"isolation": "exclusive_physical", "scheduler": "FIFO", "priority": 90},
        {"isolation": "none", "scheduler": "OTHER", "priority": 0},
    ])
    specs = expand_group_specs(p, vcpu_count=4, vhost_count=0, iothread_count=0)
    vcpu_specs = [s for s in specs if s["name"].startswith("vcpu")]
    assert vcpu_specs[0]["isolation"] == "exclusive_physical"
    assert vcpu_specs[1]["isolation"] == "none"
    assert vcpu_specs[2]["isolation"] == "none"   # last entry repeated
    assert vcpu_specs[3]["isolation"] == "none"


def test_expand_list_vcpus_longer_than_count():
    """Extra list entries beyond vcpu_count are silently ignored."""
    p = _make_profile([
        {"isolation": "exclusive_physical"},
        {"isolation": "exclusive_logical"},
        {"isolation": "none"},
    ])
    specs = expand_group_specs(p, vcpu_count=2, vhost_count=0, iothread_count=0)
    vcpu_specs = [s for s in specs if s["name"].startswith("vcpu")]
    assert len(vcpu_specs) == 2
    assert vcpu_specs[0]["isolation"] == "exclusive_physical"
    assert vcpu_specs[1]["isolation"] == "exclusive_logical"


def test_expand_order():
    """Spec order must be vCPUs → emulator → vhost → iothreads."""
    p = _make_profile({"isolation": "none"})
    specs = expand_group_specs(p, vcpu_count=2, vhost_count=1, iothread_count=1)
    names = [s["name"] for s in specs]
    assert names == ["vcpu/0", "vcpu/1", "emulator", "vhost/0", "iothread/0"]


# ------------------------------------------------------------------ count field

def test_normalize_count_passes_through():
    p = normalize_profile({"vhost": {"isolation": "exclusive_physical", "count": 2}})
    assert p["vhost"]["count"] == 2


def test_normalize_count_clamped_to_one():
    p = normalize_profile({"vhost": {"isolation": "exclusive_physical", "count": 0}})
    assert p["vhost"]["count"] == 1


def test_expand_vhost_with_count_produces_single_spec():
    """count on vhost collapses all per-thread specs into one group spec."""
    p = _make_profile({"isolation": "none"},
                      vhost={"isolation": "exclusive_physical", "count": 2})
    specs = expand_group_specs(p, vcpu_count=1, vhost_count=9, iothread_count=0)
    vhost_specs = [s for s in specs if "vhost" in s["name"]]
    assert len(vhost_specs) == 1
    assert vhost_specs[0]["name"] == "vhost"
    assert vhost_specs[0]["count"] == 2
    assert vhost_specs[0]["isolation"] == "exclusive_physical"


def test_expand_iothread_with_count_produces_single_spec():
    p = _make_profile({"isolation": "none"},
                      iothread={"isolation": "exclusive_logical", "count": 2})
    specs = expand_group_specs(p, vcpu_count=1, vhost_count=0, iothread_count=4)
    iothread_specs = [s for s in specs if "iothread" in s["name"]]
    assert len(iothread_specs) == 1
    assert iothread_specs[0]["name"] == "iothread"
    assert iothread_specs[0]["count"] == 2


def test_expand_order_with_count():
    """count on vhost preserves the vcpu → emulator → vhost → iothread order."""
    p = _make_profile({"isolation": "none"},
                      vhost={"isolation": "exclusive_physical", "count": 2})
    specs = expand_group_specs(p, vcpu_count=1, vhost_count=9, iothread_count=1)
    names = [s["name"] for s in specs]
    assert names == ["vcpu/0", "emulator", "vhost", "iothread/0"]


def test_expand_vhost_count_no_threads_skips_spec():
    """count with vhost_count=0 must not add a vhost spec."""
    p = _make_profile({"isolation": "none"},
                      vhost={"isolation": "exclusive_physical", "count": 2})
    specs = expand_group_specs(p, vcpu_count=1, vhost_count=0, iothread_count=0)
    assert not any("vhost" in s["name"] for s in specs)


# ------------------------------------------------------------------ XML parsing

_DOMAIN_XML = """
<domain type='kvm'>
  <name>testvm</name>
  <vcpu placement='static'>4</vcpu>
  <devices>
    <disk type='network' device='disk'>
      <source protocol='rbd' name='rbd/system_testvm'>
        <host name='mon1' port='6789'/>
      </source>
      <target dev='vda' bus='virtio'/>
    </disk>
  </devices>
</domain>
"""


def test_vcpu_count_from_xml():
    assert _vcpu_count_from_xml(_DOMAIN_XML) == 4


def test_vcpu_count_from_xml_empty():
    assert _vcpu_count_from_xml("") == 0


def test_vcpu_count_from_xml_prefers_current():
    """With cpu hotplug, only `current` vCPUs are present at start."""
    xml = "<domain><vcpu placement='static' current='2'>4</vcpu></domain>"
    assert _vcpu_count_from_xml(xml) == 2


def test_rbd_source_from_xml():
    assert _rbd_source_from_xml(_DOMAIN_XML) == "rbd/system_testvm"


def test_rbd_source_from_xml_no_rbd():
    xml = "<domain><devices><disk type='file'><source file='/var/lib/libvirt/x.qcow2'/></disk></devices></domain>"
    assert _rbd_source_from_xml(xml) == ""


def test_rbd_source_from_xml_empty():
    assert _rbd_source_from_xml("") == ""


# ------------------------------------------------------------------ virsh fallback

def test_get_rbd_source_virsh_skips_header(monkeypatch):
    """The domblklist header row must not be mistaken for a disk source."""
    from seapath_alloc import config
    out = (
        " Type      Device   Target   Source\n"
        "----------------------------------------\n"
        " network   disk     vda      rbd/system_vm\n"
    )
    monkeypatch.setattr(config, "_run", lambda cmd, timeout=5: out)
    assert config.get_rbd_source("vm") == "rbd/system_vm"


def test_get_rbd_source_virsh_no_rbd_disk(monkeypatch):
    from seapath_alloc import config
    out = (
        " Type   Device   Target   Source\n"
        "----------------------------------------\n"
        " file   disk     vda      /var/lib/libvirt/images/x.qcow2\n"
    )
    monkeypatch.setattr(config, "_run", lambda cmd, timeout=5: out)
    assert config.get_rbd_source("vm") == ""
