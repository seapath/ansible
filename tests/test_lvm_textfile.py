# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/deploy_prometheus_exporters/files/lvm_textfile.py."""

import json
import os
import subprocess

import pytest

from support import load_script

lvm_textfile = load_script("roles/deploy_prometheus_exporters/files/lvm_textfile.py")

# Reports in the shape lvm 2.03 prints them with --reportformat json --binary,
# taken from a SEAPATH Debian machine, plus a snapshot of root taken by an
# update and a PV that belongs to no volume group.
VGS = {
    "report": [
        {
            "vg": [
                {"vg_name": "vg1", "vg_size": "53682896896", "vg_free": "31683772416", "pv_count": "1", "vg_missing_pv_count": "0", "lv_count": "4", "snap_count": "1"},
            ]
        }
    ],
    "log": [],
}
PVS = {
    "report": [
        {
            "pv": [
                {"pv_name": "/dev/sda2", "vg_name": "vg1", "pv_size": "53682896896", "pv_free": "31683772416", "pv_missing": "0"},
                {"pv_name": "/dev/sdd", "vg_name": "", "pv_size": "1000204886016", "pv_free": "1000204886016", "pv_missing": "0"},
            ]
        }
    ]
}
LVS = {
    "report": [
        {
            "lv": [
                {"vg_name": "vg1", "lv_name": "root", "lv_size": "16106127360", "segtype": "linear", "origin": "", "pool_lv": "", "lv_active_locally": "1", "data_percent": "", "metadata_percent": "", "lv_health_status": "", "lv_merging": "0", "lv_snapshot_invalid": "-1"},
                {"vg_name": "vg1", "lv_name": "root-snap", "lv_size": "4294967296", "segtype": "linear", "origin": "root", "pool_lv": "", "lv_active_locally": "1", "data_percent": "12.50", "metadata_percent": "", "lv_health_status": "", "lv_merging": "0", "lv_snapshot_invalid": "0"},
            ]
        }
    ]
}
REPORTS = {"vgs": VGS, "pvs": PVS, "lvs": LVS}


@pytest.fixture
def fake_lvm(monkeypatch):
    """Answer each lvm report command with its canned JSON, and record the calls."""
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(REPORTS[cmd[1]]), stderr="")

    monkeypatch.setattr(lvm_textfile.subprocess, "run", run)
    return calls


def sample_lines(text):
    return [line for line in text.splitlines() if not line.startswith("#")]


@pytest.mark.parametrize(
    "text,expected",
    [("53682896896", 53682896896), ("12.50", 12.5), ("  3 ", 3), ("", None), ("  ", None)],
)
def test_number(text, expected):
    assert lvm_textfile.number(text) == expected


@pytest.mark.parametrize("text,expected", [("1", 1), ("0", 0), ("-1", None), ("", None)])
def test_flag_hides_the_unknown_value(text, expected):
    assert lvm_textfile.flag(text) == expected


@pytest.mark.parametrize("text,expected", [("12.50", 0.125), ("100.00", 1), ("", None)])
def test_ratio(text, expected):
    assert lvm_textfile.ratio(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("", 1), ("partial", 0), ("refresh needed", 0), ("mismatches exist", 0)],
)
def test_healthy(text, expected):
    assert lvm_textfile.healthy(text) == expected


def test_report_runs_lvm_with_parseable_output(fake_lvm):
    rows = lvm_textfile.report("vgs", ["vg_name", "vg_size"], "vg", 7)

    assert rows == VGS["report"][0]["vg"]
    cmd, kwargs = fake_lvm[0]
    assert cmd[:2] == ["lvm", "vgs"]
    assert cmd[-2:] == ["-o", "vg_name,vg_size"]
    for option in ("--binary", "--nosuffix", "json"):
        assert option in cmd
    assert kwargs["timeout"] == 7
    assert kwargs["check"] is True
    assert kwargs["env"]["LC_ALL"] == "C"


def test_report_skips_sections_without_the_key(monkeypatch):
    output = {"report": [{"vg": [{"vg_name": "a"}]}, {}]}
    monkeypatch.setattr(
        lvm_textfile.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(output)),
    )

    assert lvm_textfile.report("vgs", ["vg_name"], "vg", 1) == [{"vg_name": "a"}]


def test_collect_reports_every_layer(fake_lvm):
    text = lvm_textfile.render(lvm_textfile.collect(15))
    lines = sample_lines(text)

    assert 'seapath_lvm_vg_free_bytes{vg="vg1"} 31683772416' in lines
    assert 'seapath_lvm_vg_snapshot_count{vg="vg1"} 1' in lines
    assert 'seapath_lvm_pv_size_bytes{pv="/dev/sdd",vg=""} 1000204886016' in lines
    assert 'seapath_lvm_lv_info{vg="vg1",lv="root-snap",segtype="linear",origin="root",pool=""} 1' in lines
    assert 'seapath_lvm_lv_data_ratio{vg="vg1",lv="root-snap"} 0.125' in lines
    assert 'seapath_lvm_lv_snapshot_invalid{vg="vg1",lv="root-snap"} 0' in lines
    assert 'seapath_lvm_lv_healthy{vg="vg1",lv="root"} 1' in lines


def test_collect_leaves_out_the_values_that_do_not_apply(fake_lvm):
    text = lvm_textfile.render(lvm_textfile.collect(15))

    # root is no snapshot: no fill ratio and no invalid flag for it.
    assert 'seapath_lvm_lv_data_ratio{vg="vg1",lv="root"}' not in text
    assert 'seapath_lvm_lv_snapshot_invalid{vg="vg1",lv="root"}' not in text
    # No LV has metadata, so the family is not written at all.
    assert "seapath_lvm_lv_metadata_ratio" not in text


def test_render_writes_help_type_and_escaped_labels():
    families = [
        ("m_labelled", "Help.", [({"lv": 'a"b\\c\nd'}, 2)]),
        ("m_plain", "Plain.", [({}, 0.5)]),
        ("m_empty", "Empty.", []),
    ]

    assert lvm_textfile.render(families) == (
        "# HELP m_labelled Help.\n"
        "# TYPE m_labelled gauge\n"
        'm_labelled{lv="a\\"b\\\\c\\nd"} 2\n'
        "# HELP m_plain Plain.\n"
        "# TYPE m_plain gauge\n"
        "m_plain 0.5\n"
    )


def test_write_atomically_replaces_the_file(tmp_path):
    target = tmp_path / "seapath_lvm.prom"
    target.write_text("old\n")

    lvm_textfile.write_atomically(str(target), "new\n")

    assert target.read_text() == "new\n"
    assert oct(target.stat().st_mode & 0o777) == "0o644"
    assert os.listdir(tmp_path) == ["seapath_lvm.prom"]


def test_write_atomically_removes_its_temporary_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "seapath_lvm.prom"
    target.write_text("old\n")

    def replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(lvm_textfile.os, "replace", replace)
    with pytest.raises(OSError):
        lvm_textfile.write_atomically(str(target), "new\n")

    assert target.read_text() == "old\n"
    assert os.listdir(tmp_path) == ["seapath_lvm.prom"]


def test_write_atomically_in_the_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    lvm_textfile.write_atomically("seapath_lvm.prom", "x\n")

    assert (tmp_path / "seapath_lvm.prom").read_text() == "x\n"


def test_main_writes_the_metrics(fake_lvm, tmp_path):
    output = tmp_path / "seapath_lvm.prom"

    assert lvm_textfile.main(["--output", str(output), "--timeout", "3"]) == 0

    lines = sample_lines(output.read_text())
    assert "seapath_lvm_collect_success 1" in lines
    assert any(line.startswith("seapath_lvm_collect_duration_seconds ") for line in lines)
    assert 'seapath_lvm_vg_size_bytes{vg="vg1"} 53682896896' in lines
    assert all(kwargs["timeout"] == 3 for _, kwargs in fake_lvm)


def test_main_defaults(monkeypatch):
    args = lvm_textfile.parse_args([])

    assert args.output == "/var/lib/prometheus/node_exporter/seapath_lvm.prom"
    assert args.timeout == 15


@pytest.mark.parametrize(
    "error,expected",
    [
        (subprocess.TimeoutExpired(["lvm", "vgs"], 15), "timed out after 15 seconds"),
        (subprocess.CalledProcessError(5, ["lvm", "vgs"], stderr="  Volume group locked\n"), ": Volume group locked"),
        (FileNotFoundError(2, "No such file or directory", "lvm"), "No such file or directory"),
    ],
)
def test_main_on_failure_writes_only_the_failure(monkeypatch, tmp_path, capsys, error, expected):
    def run(cmd, **kwargs):
        raise error

    monkeypatch.setattr(lvm_textfile.subprocess, "run", run)
    output = tmp_path / "seapath_lvm.prom"
    output.write_text('seapath_lvm_vg_free_bytes{vg="vg1"} 1\n')

    assert lvm_textfile.main(["--output", str(output)]) == 1

    lines = sample_lines(output.read_text())
    assert lines[0] == "seapath_lvm_collect_success 0"
    assert len(lines) == 2
    assert expected in capsys.readouterr().err


def test_main_on_unparseable_output(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lvm_textfile.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout="not json"),
    )
    output = tmp_path / "seapath_lvm.prom"

    assert lvm_textfile.main(["--output", str(output)]) == 1
    assert "seapath_lvm_collect_success 0" in output.read_text()
