# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for the metric builders, state files and output of exporter.py."""

import json
import os

import pytest

from seapath_alloc import exporter as exporter_mod
from seapath_alloc.exporter import (
    clear_fallbacks,
    _build_claim_info,
    _build_cpu_detail,
    _build_irq_info,
    _build_vm_thread_info,
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
        {"comm": "CPU 0/KVM", "tid": 1001, "cpus": "4", "scheduler": "FIFO",
         "priority": 90},
        {"comm": "vhost-1000", "tid": 1010, "cpus": "5", "scheduler": "",
         "priority": 0},
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


def data(actors=(), reserved=(), free_logical="8-11",
         free_physical="8,10"):
    return {
        "isolated": "4-11",
        "free_logical": free_logical,
        "free_physical": free_physical,
        "actors": list(actors),
        "reserved_siblings": list(reserved),
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


def test_record_fallback_keeps_the_start_time_of_the_process(
        state_files, monkeypatch):
    monkeypatch.setattr(exporter_mod, "process_start_time",
                        lambda pid, proc="/proc": 777)

    record_fallback("vm0", "vcpu/0", "exclusive_physical", pid=4242)

    assert _load_active()["vm0::vcpu/0"]["start"] == 777


@pytest.mark.parametrize("entry, exists, start, alive", [
    ({}, False, None, True),                        # no pid: never lapses
    ({"pid": 4242}, False, None, False),            # gone
    ({"pid": 4242}, True, None, True),              # no start recorded
    ({"pid": 4242, "start": 777}, True, 777, True),
    ({"pid": 4242, "start": 777}, True, 999, False),  # PID recycled
    ({"pid": 4242, "start": 777}, True, None, True),  # stat unreadable
])
def test_an_active_entry_lives_as_long_as_its_process(
        monkeypatch, entry, exists, start, alive):
    monkeypatch.setattr(exporter_mod.os.path, "exists", lambda p: exists)
    monkeypatch.setattr(exporter_mod, "process_start_time",
                        lambda pid, proc="/proc": start)

    assert exporter_mod._entry_alive(entry) is alive


# --- _metric --------------------------------------------------------------

def test_metric_writes_help_type_and_samples():
    buf = []

    _metric(buf, "m", "a help text", "gauge", [({"a": "1"}, 5)])

    assert buf == [
        "# HELP m a help text",
        "# TYPE m gauge",
        'm{a="1"} 5',
    ]


def test_metric_escapes_label_values():
    buf = []

    _metric(buf, "x", "h", "gauge", [({"label": 'a"b\\c\nd'}, 1)])

    assert buf[-1] == 'x{label="a\\"b\\\\c\\nd"} 1'


def test_metric_without_labels():
    buf = []

    _metric(buf, "m", "h", "gauge", [({}, 7)])

    assert buf[-1] == "m 7"


def test_metric_with_no_samples_writes_nothing():
    buf = []

    _metric(buf, "m", "h", "gauge", [])

    assert buf == []


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
        "vm": "vm0", "thread": "CPU 0/KVM", "tid": "1001", "cpu": "4",
        "scheduler": "FIFO", "priority": "90",
    }


def test_vm_thread_info_keeps_vhost_workers_of_one_vm_apart():
    # Every vhost worker of a VM has the comm vhost-<qemu pid>; on one core
    # with one policy they would otherwise be the same series twice.
    vm = {"type": "vm", "label": "vm0", "threads": [
        {"comm": "vhost-1000", "tid": tid, "cpus": "5", "scheduler": "FIFO",
         "priority": 1}
        for tid in (1010, 1011)
    ]}

    samples = _build_vm_thread_info(data(actors=[vm]))

    assert len({tuple(s[0].items()) for s in samples}) == 2


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


def test_occupied_cpu_counts_sums_vm_threads_and_other_actors():
    samples = _occupied_cpu_counts(data(actors=[VM, IRQ, CLAIM]))

    assert samples == [({"type": "irq"}, 1), ({"type": "quadlet"}, 1),
                       ({"type": "vm"}, 2)]


def test_occupied_cpu_counts_count_a_shared_core_once():
    vm = {"type": "vm", "label": "vm0", "threads": [
        {"comm": "qemu-system-x86", "cpus": "4", "scheduler": "", "priority": 0},
        {"comm": "IO iothread1", "cpus": "4", "scheduler": "", "priority": 0},
        {"comm": "vhost-1000", "cpus": "4-5", "scheduler": "", "priority": 0},
    ]}

    assert _occupied_cpu_counts(data(actors=[vm])) == [({"type": "vm"}, 2)]


def test_occupied_cpu_counts_leave_out_the_housekeeping_cores():
    fallback = dict(CLAIM, cpus="0-3")

    assert _occupied_cpu_counts(data(actors=[fallback])) == [
        ({"type": "quadlet"}, 0)]


def test_occupied_cpu_counts_of_an_idle_node():
    assert _occupied_cpu_counts(data()) == []


# --- generate -------------------------------------------------------------


@pytest.fixture
def node(monkeypatch, state_files, std_topology):
    """Serve a canned collect() payload and topology to generate()."""
    def install(payload=None):
        monkeypatch.setattr(
            exporter_mod, "collect", lambda: payload or data()
        )
        monkeypatch.setattr(exporter_mod, "Topology", lambda **kw: std_topology)
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
    # The exporter only filters: the file is pruned by the allocation
    # pipeline, under the pool flock, so a scrape never races a hook.
    assert list(_load_active()) == ["vm0::vcpu/0"]
    record_fallback("vm1", "vcpu/0", "exclusive_physical", pid=4243)
    assert list(_load_active()) == ["vm1::vcpu/0"]


def test_a_state_file_that_cannot_be_written_never_fails_the_caller(
    node, state_files, monkeypatch, caplog
):
    monkeypatch.setattr(exporter_mod.os.path, "exists", lambda p: True)
    record_fallback("vm0", "vcpu/1", "exclusive_physical", pid=4242)

    def refuse(path, data):
        raise OSError("read-only file system")

    monkeypatch.setattr(exporter_mod, "_write_json", refuse)

    with caplog.at_level("WARNING", logger=exporter_mod.log.name):
        record_fallback("vm0", "vcpu/0", "exclusive_physical", pid=4242)
        clear_fallbacks("vm0", ["vcpu/1"])

    assert "could not record the fallback of vm0 vcpu/0" in caplog.text
    assert "could not update the active fallbacks of vm0" in caplog.text


def test_clearing_forgets_only_the_groups_allocated_as_asked(
    node, state_files, monkeypatch
):
    monkeypatch.setattr(exporter_mod.os.path, "exists", lambda p: True)
    record_fallback("vm0", "vcpu/0", "exclusive_physical", pid=4242)
    record_fallback("vm0", "vcpu/1", "exclusive_physical", pid=4242)

    clear_fallbacks("vm0", ["vcpu/0", "emulator"])

    assert list(_load_active()) == ["vm0::vcpu/1"]


def test_clearing_with_nothing_to_forget_writes_nothing(
    node, state_files, monkeypatch
):
    writes = []
    monkeypatch.setattr(exporter_mod, "_write_json",
                        lambda path, data: writes.append(path))

    clear_fallbacks("vm0", ["vcpu/0"])

    assert writes == []


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
