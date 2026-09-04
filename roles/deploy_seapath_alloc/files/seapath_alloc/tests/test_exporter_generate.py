# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for the metric builders, state files and output of exporter.py."""

import json
import os

import pytest

from seapath_alloc import exporter as exporter_mod
from seapath_alloc.exporter import (
    _build_claim_info,
    _build_cpu_detail,
    _build_irq_info,
    _build_slot_member_info,
    _build_slot_warning_info,
    _build_vm_thread_info,
    _escape,
    _load_active,
    _load_state,
    _metric,
    _occupied_cpu_counts,
    _write_json,
    generate,
    record_fallback,
    write_prom,
)

VM = {
    "type": "vm", "label": "vm0",
    "threads": [
        {"comm": "CPU 0/KVM", "cpus": "4", "scheduler": "FIFO", "priority": 90},
        {"comm": "vhost-1000", "cpus": "5", "scheduler": "", "priority": 0},
    ],
}
IRQ = {"type": "irq", "label": "eno1/181", "iface": "eno1", "irqs": "181",
       "cpus": "6"}
CLAIM = {"type": "quadlet", "label": "redis", "cpus": "7", "pid": 4242,
         "scheduler": "FIFO", "priority": 10}


@pytest.fixture
def state_files(tmp_path, monkeypatch):
    """Point the two persistent state files at a temporary directory."""
    state = tmp_path / "alloc" / "fallbacks.json"
    active = tmp_path / "alloc" / "active_fallbacks.json"
    monkeypatch.setattr(exporter_mod, "_STATE_PATH", str(state))
    monkeypatch.setattr(exporter_mod, "_ACTIVE_PATH", str(active))
    return state, active


def data(actors=(), slots=(), reserved=(), free_logical="8-11",
         free_physical="8,10"):
    return {
        "isolated": "4-11",
        "free_logical": free_logical,
        "free_physical": free_physical,
        "actors": list(actors),
        "reserved_siblings": list(reserved),
        "slots": list(slots),
    }


def tuning(tuned=None, cmdline="BOOT_IMAGE=/vmlinuz isolcpus=4-11",
           sched_rt=None, hugepages=None, thp=None, smt=None, acpi=True,
           irq=None):
    """A canned host reading, shaped like conformance.collect()."""
    return {
        "tuned": tuned if tuned is not None else {
            "profile": "seapath-rt-host",
            "source": "/etc/tuned/active_profile",
            "installed": True,
        },
        "cmdline": cmdline,
        "sched_rt": sched_rt if sched_rt is not None else {
            "runtime_us": -1, "period_us": 1000000,
        },
        "hugepages": hugepages if hugepages is not None else [
            {"size_kb": 1048576, "node": None, "total": 16, "free": 8},
        ],
        "thp": thp if thp is not None else {
            "enabled": "never", "defrag": "never",
        },
        "smt": smt if smt is not None else {"active": True, "control": "on"},
        "acpi": acpi,
        "irq": irq if irq is not None else {
            "total": 214, "on_isolated": 0, "detail": [],
        },
    }


def families(text):
    """Map metric name -> list of sample lines."""
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or not line:
            continue
        name = line.split("{")[0].split(" ")[0]
        out.setdefault(name, []).append(line)
    return out


# --- state files ----------------------------------------------------------


def test_state_defaults_when_the_file_is_absent(state_files):
    assert _load_state() == {
        "total": 0, "last_ts": 0, "last_label": "", "last_group": "",
        "last_requested": "", "last_severity": "",
    }


def test_state_defaults_when_the_file_is_corrupt(state_files):
    state, _ = state_files
    state.parent.mkdir(parents=True)
    state.write_text("{not json")

    assert _load_state()["total"] == 0


def test_active_defaults_to_empty(state_files):
    assert _load_active() == {}


def test_active_defaults_when_the_file_is_corrupt(state_files):
    _, active = state_files
    active.parent.mkdir(parents=True)
    active.write_text("[")

    assert _load_active() == {}


def test_write_json_creates_the_directory_and_replaces_atomically(tmp_path):
    path = tmp_path / "deep" / "state.json"

    _write_json(str(path), {"total": 3})

    assert json.loads(path.read_text()) == {"total": 3}
    # The temporary file is renamed, never left behind.
    assert not (tmp_path / "deep" / "state.json.tmp").exists()


# --- record_fallback ------------------------------------------------------


def test_record_fallback_counts_the_event(state_files):
    record_fallback("vm0", "vcpu/0", "exclusive_physical")

    state = _load_state()
    assert state["total"] == 1
    assert state["last_label"] == "vm0"
    assert state["last_group"] == "vcpu/0"
    assert state["last_requested"] == "exclusive_physical"
    assert state["last_severity"] == "hard"
    assert state["last_ts"] > 0


def test_record_fallback_accumulates(state_files):
    record_fallback("vm0", "vcpu/0", "exclusive_physical")
    record_fallback("vm1", "vcpu/0", "exclusive_logical", severity="soft")

    state = _load_state()
    assert state["total"] == 2
    assert state["last_label"] == "vm1"
    assert state["last_severity"] == "soft"


def test_record_fallback_without_a_pid_tracks_nothing_active(state_files):
    record_fallback("vm0", "vcpu/0", "exclusive_physical")

    assert _load_active() == {}


def test_record_fallback_with_a_pid_marks_the_actor_degraded(state_files):
    record_fallback("vm0", "vcpu/0", "exclusive_physical", pid=4242,
                    severity="soft")

    entry = _load_active()["vm0::vcpu/0"]
    assert entry["label"] == "vm0"
    assert entry["group"] == "vcpu/0"
    assert entry["requested"] == "exclusive_physical"
    assert entry["severity"] == "soft"
    assert entry["pid"] == 4242
    assert entry["since"] > 0


# --- _metric --------------------------------------------------------------

def test_metric_writes_help_type_and_samples():
    buf = []

    _metric(buf, "m", "a help text", "gauge", [({"a": "1"}, 5)])

    assert buf == [
        "# HELP m a help text",
        "# TYPE m gauge",
        'm{a="1"} 5',
    ]


def test_metric_without_labels():
    buf = []

    _metric(buf, "m", "h", "gauge", [({}, 7)])

    assert buf[-1] == "m 7"


def test_metric_with_no_samples_writes_nothing():
    buf = []

    _metric(buf, "m", "h", "gauge", [])

    assert buf == []


def test_escape_leaves_an_ordinary_label_alone():
    assert _escape("eno1-TxRx-0") == "eno1-TxRx-0"


def test_escape_protects_the_three_reserved_characters():
    assert _escape(r'a\b "c" d' + "\ne") == r'a\\b \"c\" d\ne'


def test_metric_escapes_label_values():
    buf = []
    _metric(buf, "m", "h", "gauge", [({"cmdline": 'quiet dyndbg="x +p"'}, 1)])

    assert buf[-1] == r'm{cmdline="quiet dyndbg=\"x +p\""} 1'


# --- per-actor builders ---------------------------------------------------


def test_cpu_detail_marks_reserved_ht_siblings(std_topology):
    samples = _build_cpu_detail(data(reserved=[(5, 4)]), std_topology)

    by_cpu = {s[0]["cpu"]: s[0] for s in samples}
    assert by_cpu["5"]["state"] == "reserved"
    assert by_cpu["5"]["label"] == "4"
    assert by_cpu["5"]["group"] == "ht_sibling"


def test_cpu_detail_marks_irq_and_other_actors(std_topology):
    samples = _build_cpu_detail(data(actors=[IRQ, CLAIM]), std_topology)

    by_cpu = {s[0]["cpu"]: s[0] for s in samples}
    assert by_cpu["6"]["state"] == "irq"
    assert by_cpu["6"]["label"] == "eno1/181"
    assert by_cpu["7"]["state"] == "quadlet"
    assert by_cpu["7"]["scheduler"] == "FIFO"
    assert by_cpu["7"]["priority"] == "10"


def test_cpu_detail_separates_isolated_from_housekeeping(std_topology):
    samples = _build_cpu_detail(data(), std_topology)

    by_cpu = {s[0]["cpu"]: s[0] for s in samples}
    assert by_cpu["0"]["state"] == "housekeeping"
    assert by_cpu["0"]["isolated"] == "0"
    assert by_cpu["4"]["state"] == "free"
    assert by_cpu["4"]["isolated"] == "1"


def test_vm_thread_info_has_one_sample_per_thread():
    samples = _build_vm_thread_info(data(actors=[VM, IRQ]))

    assert [s[0]["thread"] for s in samples] == ["CPU 0/KVM", "vhost-1000"]
    assert samples[0][0] == {
        "vm": "vm0", "thread": "CPU 0/KVM", "cpu": "4",
        "scheduler": "FIFO", "priority": "90",
    }


def test_vm_thread_info_of_a_vm_with_no_threads():
    assert _build_vm_thread_info(data(actors=[{"type": "vm", "label": "vm0"}])) == []


def test_irq_info_has_one_sample_per_irq_group():
    samples = _build_irq_info(data(actors=[VM, IRQ]))

    assert samples == [({"iface": "eno1", "irq_range": "181", "cpu": "6"}, 1)]


def test_claim_info_covers_every_non_vm_non_irq_actor():
    samples = _build_claim_info(data(actors=[VM, IRQ, CLAIM]))

    assert samples == [({
        "kind": "quadlet", "label": "redis", "cpu": "7",
        "scheduler": "FIFO", "priority": "10", "pid": "4242",
    }, 1)]


def test_slot_member_info_has_one_sample_per_member():
    slots = [{
        "name": "rt", "cores": "10", "isolation": "shared",
        "members": [{"kind": "vm", "label": "vm0", "group": "CPU 0/KVM",
                     "scheduler": "FIFO", "priority": 80, "cpus": "10"}],
        "warnings": [],
    }]

    samples = _build_slot_member_info(data(slots=slots))

    assert samples == [({
        "slot": "rt", "kind": "vm", "label": "vm0", "group": "CPU 0/KVM",
        "scheduler": "FIFO", "priority": "80", "cpu": "10",
    }, 1)]


def test_slot_warning_info_has_one_sample_per_reason():
    slots = [{"name": "rt", "cores": "10", "members": [],
              "warnings": ["equal_rt_priority", "vcpu_shared"]}]

    samples = _build_slot_warning_info(data(slots=slots))

    assert [s[0]["reason"] for s in samples] == ["equal_rt_priority",
                                                 "vcpu_shared"]


def test_occupied_cpu_counts_sums_vm_threads_and_other_actors():
    samples = _occupied_cpu_counts(data(actors=[VM, IRQ, CLAIM]))

    assert samples == [({"type": "irq"}, 1), ({"type": "quadlet"}, 1),
                       ({"type": "vm"}, 2)]


def test_occupied_cpu_counts_of_an_idle_node():
    assert _occupied_cpu_counts(data()) == []


# --- generate -------------------------------------------------------------


@pytest.fixture
def node(monkeypatch, state_files, std_topology):
    """Serve a canned collect() payload, topology and host reading.

    The host reading is canned too: generate() reads the machine it runs on,
    and a test that let it through would assert on the developer's laptop.
    """
    def install(payload=None, host=None):
        monkeypatch.setattr(
            exporter_mod, "collect", lambda: payload or data()
        )
        monkeypatch.setattr(exporter_mod, "Topology", lambda **kw: std_topology)
        monkeypatch.setattr(
            exporter_mod.conformance, "collect",
            lambda **kw: host if host is not None else tuning()
        )
        return payload

    return install


def test_generate_reports_the_pool_summary(node):
    node(data(actors=[VM, IRQ, CLAIM]))

    out = families(generate())

    assert out["seapath_alloc_isolated_cpus"] == ["seapath_alloc_isolated_cpus 8"]
    assert out["seapath_alloc_free_logical_cpus"] == [
        "seapath_alloc_free_logical_cpus 4"
    ]
    assert out["seapath_alloc_free_physical_pairs"] == [
        "seapath_alloc_free_physical_pairs 2"
    ]


def test_generate_reports_zero_when_nothing_is_free(node):
    node(data(free_logical="", free_physical=""))

    out = families(generate())

    assert out["seapath_alloc_free_logical_cpus"] == [
        "seapath_alloc_free_logical_cpus 0"
    ]
    assert out["seapath_alloc_free_physical_pairs"] == [
        "seapath_alloc_free_physical_pairs 0"
    ]


def test_generate_counts_actors_by_type(node):
    node(data(actors=[VM, IRQ, CLAIM]))

    out = families(generate())

    assert sorted(out["seapath_alloc_actors"]) == [
        'seapath_alloc_actors{type="irq"} 1',
        'seapath_alloc_actors{type="quadlet"} 1',
        'seapath_alloc_actors{type="vm"} 1',
    ]
    assert out["seapath_alloc_vm_threads"] == [
        'seapath_alloc_vm_threads{vm="vm0"} 2'
    ]


def test_generate_reports_slots_and_their_members(node):
    slots = [{
        "name": "rt", "cores": "10", "isolation": "shared",
        "members": [{"kind": "vm", "label": "vm0", "group": "CPU 0/KVM",
                     "scheduler": "FIFO", "priority": 80, "cpus": "10"}],
        "warnings": ["vcpu_shared"],
    }]
    node(data(slots=slots))

    out = families(generate())

    assert out["seapath_alloc_slots"] == ["seapath_alloc_slots 1"]
    assert out["seapath_alloc_slot_members"] == [
        'seapath_alloc_slot_members{slot="rt"} 1'
    ]
    assert "seapath_alloc_slot_member_info" in out
    assert 'reason="vcpu_shared"' in out["seapath_alloc_slot_warning_info"][0]


def test_generate_always_stamps_the_scrape_time(node):
    node()

    out = families(generate())

    assert out["seapath_alloc_scrape_timestamp_seconds"][0].split()[-1].isdigit()


def test_generate_reports_no_fallback_context_when_there_was_none(node):
    node()

    out = families(generate())

    assert out["seapath_alloc_allocation_fallbacks_total"] == [
        "seapath_alloc_allocation_fallbacks_total 0"
    ]
    assert "seapath_alloc_last_fallback_timestamp_seconds" not in out
    assert "seapath_alloc_last_fallback_info" not in out


def test_generate_reports_the_last_fallback(node, state_files):
    node()
    record_fallback("vm0", "vcpu/0", "exclusive_physical", severity="soft")

    out = families(generate())

    assert out["seapath_alloc_allocation_fallbacks_total"] == [
        "seapath_alloc_allocation_fallbacks_total 1"
    ]
    assert "seapath_alloc_last_fallback_timestamp_seconds" in out
    info = out["seapath_alloc_last_fallback_info"][0]
    assert 'label="vm0"' in info and 'severity="soft"' in info


def test_generate_counts_actors_still_degraded(node, state_files, monkeypatch):
    node()
    monkeypatch.setattr(exporter_mod.os.path, "exists", lambda p: True)
    record_fallback("vm0", "vcpu/0", "exclusive_physical", pid=4242)
    record_fallback("vm1", "vcpu/0", "exclusive_physical", pid=4243,
                    severity="soft")

    out = families(generate())

    assert sorted(out["seapath_alloc_active_fallbacks"]) == [
        'seapath_alloc_active_fallbacks{severity="hard"} 1',
        'seapath_alloc_active_fallbacks{severity="soft"} 1',
    ]
    assert len(out["seapath_alloc_active_fallback_info"]) == 2


def test_generate_expires_a_degraded_actor_that_exited(
    node, state_files, monkeypatch
):
    node()
    monkeypatch.setattr(exporter_mod.os.path, "exists", lambda p: True)
    record_fallback("vm0", "vcpu/0", "exclusive_physical", pid=4242)

    # The process is gone on the next scrape.
    monkeypatch.setattr(exporter_mod.os.path, "exists", lambda p: False)
    out = families(generate())

    assert out["seapath_alloc_active_fallbacks"] == [
        'seapath_alloc_active_fallbacks{severity="hard"} 0',
        'seapath_alloc_active_fallbacks{severity="soft"} 0',
    ]
    assert "seapath_alloc_active_fallback_info" not in out
    # The expiry is persisted, not recomputed on every scrape.
    assert _load_active() == {}


def test_generate_keeps_a_degraded_actor_with_no_pid(node, state_files):
    node()
    _write_json(exporter_mod._ACTIVE_PATH, {"vm0::vcpu/0": {
        "label": "vm0", "group": "vcpu/0", "requested": "exclusive_physical",
        "severity": "hard", "since": 1, "pid": 0,
    }})

    out = families(generate())

    assert 'seapath_alloc_active_fallbacks{severity="hard"} 1' in out[
        "seapath_alloc_active_fallbacks"
    ]


# --- write_prom -----------------------------------------------------------


def test_write_prom_publishes_the_file_atomically(node, tmp_path):
    node(data(actors=[VM]))
    path = tmp_path / "textfile" / "seapath-alloc.prom"

    write_prom(str(path))

    content = path.read_text()
    assert content.startswith("# HELP seapath_alloc_isolated_cpus")
    assert content.endswith("\n")
    # node_exporter must never see a partial file.
    assert not (tmp_path / "textfile" / "seapath-alloc.prom.tmp").exists()


def test_write_prom_overwrites_a_previous_scrape(node, tmp_path):
    node()
    path = tmp_path / "seapath-alloc.prom"
    path.write_text("stale content\n")

    write_prom(str(path))

    assert "stale content" not in path.read_text()


# --- host real-time tuning ------------------------------------------------
#
# The families a management interface reads to ask the eight conformance
# questions of every node in a cluster instead of only of the one it runs on.
# Two conventions are load bearing there and are asserted here: an info family
# is published even when the reading was empty, so an absent family means the
# node runs an older collector, and a numeric gauge is omitted rather than
# defaulted, because every value it could carry is a legitimate one.


def test_generate_publishes_the_tuned_profile(node):
    node(host=tuning())

    out = families(generate())

    assert out["seapath_rt_tuned_info"] == [
        'seapath_rt_tuned_info{profile="seapath-rt-host",'
        'source="/etc/tuned/active_profile",installed="1"} 1'
    ]


def test_generate_publishes_a_profile_installed_nowhere(node):
    node(host=tuning(tuned={
        "profile": "seapath-rt-host",
        "source": "/etc/tuned/active_profile",
        "installed": False,
    }))

    assert 'installed="0"' in families(generate())["seapath_rt_tuned_info"][0]


def test_generate_publishes_the_tuned_family_when_no_profile_was_read(node):
    """An empty label is a reading. An absent family is an older collector."""
    node(host=tuning(tuned={"profile": "", "source": "", "installed": None}))

    assert families(generate())["seapath_rt_tuned_info"] == [
        'seapath_rt_tuned_info{profile="",source="",installed=""} 1'
    ]


def test_generate_publishes_the_kernel_command_line_verbatim(node):
    node(host=tuning(cmdline="BOOT_IMAGE=/vmlinuz isolcpus=4-11 nohz_full=4-11"))

    assert families(generate())["seapath_rt_kernel_cmdline_info"] == [
        'seapath_rt_kernel_cmdline_info{cmdline="BOOT_IMAGE=/vmlinuz '
        'isolcpus=4-11 nohz_full=4-11"} 1'
    ]


def test_generate_escapes_a_command_line_that_would_break_the_exposition(node):
    node(host=tuning(cmdline='root=UUID=x quiet dyndbg="module nvme +p"'))

    line = families(generate())["seapath_rt_kernel_cmdline_info"][0]

    assert r'dyndbg=\"module nvme +p\"' in line


def test_generate_publishes_the_rt_throttling_window(node):
    node(host=tuning(sched_rt={"runtime_us": -1, "period_us": 1000000}))

    out = families(generate())

    assert out["seapath_rt_sched_rt_runtime_us"] == [
        "seapath_rt_sched_rt_runtime_us -1"
    ]
    assert out["seapath_rt_sched_rt_period_us"] == [
        "seapath_rt_sched_rt_period_us 1000000"
    ]


def test_generate_omits_a_sysctl_it_could_not_read(node):
    """Absent rather than defaulted: -1 and 950000 are both real answers."""
    node(host=tuning(sched_rt={"runtime_us": None, "period_us": None}))

    out = families(generate())

    assert "seapath_rt_sched_rt_runtime_us" not in out
    assert "seapath_rt_sched_rt_period_us" not in out


def test_generate_publishes_hugepages_per_size_and_numa_node(node):
    node(host=tuning(hugepages=[
        {"size_kb": 1048576, "node": None, "total": 16, "free": 8},
        {"size_kb": 1048576, "node": 0, "total": 16, "free": 8},
        {"size_kb": 1048576, "node": 1, "total": 0, "free": 0},
    ]))

    out = families(generate())

    assert out["seapath_rt_hugepages_total"] == [
        'seapath_rt_hugepages_total{size_kb="1048576",node=""} 16',
        'seapath_rt_hugepages_total{size_kb="1048576",node="0"} 16',
        'seapath_rt_hugepages_total{size_kb="1048576",node="1"} 0',
    ]
    assert 'seapath_rt_hugepages_free{size_kb="1048576",node="1"} 0' in out[
        "seapath_rt_hugepages_free"
    ]


def test_generate_publishes_no_hugepage_family_on_a_kernel_with_no_pool(node):
    node(host=tuning(hugepages=[]))

    assert "seapath_rt_hugepages_total" not in families(generate())


def test_generate_publishes_the_transparent_hugepage_controls(node):
    node(host=tuning(thp={"enabled": "madvise", "defrag": "defer"}))

    assert families(generate())["seapath_rt_transparent_hugepages_info"] == [
        'seapath_rt_transparent_hugepages_info{enabled="madvise",'
        'defrag="defer"} 1'
    ]


def test_generate_publishes_smt(node):
    node(host=tuning(smt={"active": True, "control": "on"}))

    out = families(generate())

    assert out["seapath_rt_smt_info"] == ['seapath_rt_smt_info{control="on"} 1']
    assert out["seapath_rt_smt_active"] == ["seapath_rt_smt_active 1"]


def test_generate_keeps_smt_off_apart_from_a_machine_with_no_control(node):
    node(host=tuning(smt={"active": False, "control": "off"}))

    assert families(generate())["seapath_rt_smt_active"] == [
        "seapath_rt_smt_active 0"
    ]


def test_generate_omits_smt_active_where_the_machine_exposes_none(node):
    node(host=tuning(smt={"active": None, "control": ""}))

    out = families(generate())

    assert "seapath_rt_smt_active" not in out
    assert out["seapath_rt_smt_info"] == ['seapath_rt_smt_info{control=""} 1']


def test_generate_publishes_acpi(node):
    node(host=tuning(acpi=False))

    assert families(generate())["seapath_rt_acpi_present"] == [
        "seapath_rt_acpi_present 0"
    ]


def test_generate_publishes_the_interrupts_reaching_isolated_cpus(node):
    node(host=tuning(irq={
        "total": 214,
        "on_isolated": 2,
        "detail": [
            {"irq": "181", "name": "eno1-TxRx-0", "cpus": [4, 5]},
            {"irq": "182", "name": "", "cpus": [6]},
        ],
    }))

    out = families(generate())

    assert out["seapath_rt_irqs_total"] == ["seapath_rt_irqs_total 214"]
    assert out["seapath_rt_irqs_on_isolated_cpus"] == [
        "seapath_rt_irqs_on_isolated_cpus 2"
    ]
    assert out["seapath_rt_irq_on_isolated_info"] == [
        'seapath_rt_irq_on_isolated_info{irq="181",name="eno1-TxRx-0",'
        'cpus="4,5"} 1',
        'seapath_rt_irq_on_isolated_info{irq="182",name="",cpus="6"} 1',
    ]


def test_generate_publishes_a_clean_irq_affinity_as_zero(node):
    """Zero is the expected shape, and it has to be said rather than implied."""
    node(host=tuning(irq={"total": 214, "on_isolated": 0, "detail": []}))

    out = families(generate())

    assert out["seapath_rt_irqs_on_isolated_cpus"] == [
        "seapath_rt_irqs_on_isolated_cpus 0"
    ]
    assert "seapath_rt_irq_on_isolated_info" not in out


def test_generate_omits_the_irq_families_when_proc_irq_said_nothing(node):
    node(host=tuning(irq={"total": None, "on_isolated": 0, "detail": []}))

    out = families(generate())

    assert "seapath_rt_irqs_total" not in out
    assert "seapath_rt_irqs_on_isolated_cpus" not in out


def test_generate_reads_the_host_with_the_isolated_set_it_already_has(node,
                                                                     monkeypatch):
    """The topology is read once. A second reading could only disagree."""
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return tuning()

    node()
    monkeypatch.setattr(exporter_mod.conformance, "collect", spy)

    generate()

    assert seen["isolated"] == [4, 5, 6, 7, 8, 9, 10, 11]


def test_generate_publishes_both_blocks_in_one_file(node, tmp_path):
    """One textfile, one timer, one node_exporter job."""
    node()
    path = tmp_path / "seapath-alloc.prom"

    write_prom(str(path))

    content = path.read_text()
    assert "seapath_alloc_cpu_detail" in content
    assert "seapath_rt_tuned_info" in content
