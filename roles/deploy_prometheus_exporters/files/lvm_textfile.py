#!/usr/bin/env python3
# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Write the state of LVM to the node_exporter textfile collector.

node_exporter reports the file systems mounted on logical volumes and the I/O
of their device-mapper devices, but nothing of the LVM layer itself: the room
left in a volume group, how full a snapshot or a thin pool is, whether a
logical volume is degraded. This script reads them from vgs, pvs and lvs and
writes them to a .prom file, which node_exporter serves on its next scrape.

A systemd timer runs it. A run that fails writes seapath_lvm_collect_success 0
and nothing else, so that Prometheus never serves the figures of an earlier
run as current ones.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

DEFAULT_OUTPUT = "/var/lib/prometheus/node_exporter/seapath_lvm.prom"
DEFAULT_TIMEOUT = 15

# Sizes in bytes without a unit suffix, and the binary fields as 0 or 1
# instead of a word, so that every value parses as a number.
REPORT_OPTIONS = ["--reportformat", "json", "--units", "b", "--nosuffix", "--binary"]

VG_FIELDS = [
    "vg_name",
    "vg_size",
    "vg_free",
    "pv_count",
    "vg_missing_pv_count",
    "lv_count",
    "snap_count",
]
PV_FIELDS = ["pv_name", "vg_name", "pv_size", "pv_free", "pv_missing"]
LV_FIELDS = [
    "vg_name",
    "lv_name",
    "lv_size",
    "segtype",
    "origin",
    "pool_lv",
    "lv_active_locally",
    "data_percent",
    "metadata_percent",
    "lv_health_status",
    "lv_merging",
    "lv_snapshot_invalid",
]


def number(text):
    """The value of a numeric field, or None when the field does not apply."""
    text = text.strip()
    if not text:
        return None
    value = float(text)
    return int(value) if value.is_integer() else value


def flag(text):
    """A binary field, or None when LVM reports it as unknown (-1)."""
    value = number(text)
    if value is None or value < 0:
        return None
    return value


def ratio(text):
    """A percentage field as a ratio between 0 and 1."""
    value = number(text)
    if value is None:
        return None
    return value / 100


def healthy(text):
    """1 when lv_health_status is empty, which is how LVM reports a sound LV."""
    return 0 if text.strip() else 1


# Each entry: metric name, help text, lvs field and the conversion applied.
VG_METRICS = [
    ("seapath_lvm_vg_size_bytes", "Size of the volume group.", "vg_size", number),
    ("seapath_lvm_vg_free_bytes", "Unallocated space in the volume group.", "vg_free", number),
    ("seapath_lvm_vg_pv_count", "Physical volumes in the volume group.", "pv_count", number),
    ("seapath_lvm_vg_missing_pv_count", "Physical volumes of the volume group that cannot be found.", "vg_missing_pv_count", number),
    ("seapath_lvm_vg_lv_count", "Logical volumes in the volume group.", "lv_count", number),
    ("seapath_lvm_vg_snapshot_count", "Snapshots in the volume group.", "snap_count", number),
]
PV_METRICS = [
    ("seapath_lvm_pv_size_bytes", "Size of the physical volume.", "pv_size", number),
    ("seapath_lvm_pv_free_bytes", "Unallocated space on the physical volume.", "pv_free", number),
    ("seapath_lvm_pv_missing", "1 when the physical volume cannot be found.", "pv_missing", flag),
]
LV_METRICS = [
    ("seapath_lvm_lv_size_bytes", "Size of the logical volume.", "lv_size", number),
    ("seapath_lvm_lv_active", "1 when the logical volume is active on this node.", "lv_active_locally", flag),
    ("seapath_lvm_lv_data_ratio", "Used share of a snapshot, thin pool or thin volume.", "data_percent", ratio),
    ("seapath_lvm_lv_metadata_ratio", "Used share of the metadata of a thin or cache pool.", "metadata_percent", ratio),
    ("seapath_lvm_lv_healthy", "0 when lv_health_status reports a problem (partial, refresh needed, mismatches exist).", "lv_health_status", healthy),
    ("seapath_lvm_lv_merging", "1 while a snapshot is being merged back into its origin.", "lv_merging", flag),
    ("seapath_lvm_lv_snapshot_invalid", "1 when a snapshot has overflowed and can no longer be used.", "lv_snapshot_invalid", flag),
]


def report(command, fields, key, timeout):
    """Run one LVM report command and return its rows."""
    result = subprocess.run(
        ["lvm", command, *REPORT_OPTIONS, "-o", ",".join(fields)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        # A French locale would print the percentages with a decimal comma.
        env={**os.environ, "LC_ALL": "C", "LVM_SUPPRESS_FD_WARNINGS": "1"},
    )
    rows = []
    for section in json.loads(result.stdout)["report"]:
        rows.extend(section.get(key, []))
    return rows


def vg_labels(row):
    return {"vg": row["vg_name"]}


def pv_labels(row):
    return {"pv": row["pv_name"], "vg": row["vg_name"]}


def lv_labels(row):
    return {"vg": row["vg_name"], "lv": row["lv_name"]}


def families_from(rows, metrics, labels):
    """One family per metric, holding a sample for every row where it applies."""
    families = []
    for name, help_text, field, convert in metrics:
        samples = []
        for row in rows:
            value = convert(row[field])
            if value is not None:
                samples.append((labels(row), value))
        families.append((name, help_text, samples))
    return families


def lv_info(rows):
    samples = [
        (
            {
                **lv_labels(row),
                "segtype": row["segtype"],
                "origin": row["origin"],
                "pool": row["pool_lv"],
            },
            1,
        )
        for row in rows
    ]
    return ("seapath_lvm_lv_info", "Type of the logical volume, and the origin of a snapshot or the pool of a thin volume.", samples)


def collect(timeout):
    vgs = report("vgs", VG_FIELDS, "vg", timeout)
    pvs = report("pvs", PV_FIELDS, "pv", timeout)
    lvs = report("lvs", LV_FIELDS, "lv", timeout)
    return (
        families_from(vgs, VG_METRICS, vg_labels)
        + families_from(pvs, PV_METRICS, pv_labels)
        + [lv_info(lvs)]
        + families_from(lvs, LV_METRICS, lv_labels)
    )


def escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(families):
    lines = []
    for name, help_text, samples in families:
        if not samples:
            continue
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        for labels, value in samples:
            if labels:
                pairs = ",".join(f'{key}="{escape(val)}"' for key, val in labels.items())
                lines.append(f"{name}{{{pairs}}} {value}")
            else:
                lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


def write_atomically(path, text):
    """
    Replace the file in one rename, so node_exporter never reads half of it.

    The temporary file does not end in .prom, which keeps the textfile
    collector from reading it.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".seapath_lvm.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as tmpfile:
            tmpfile.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="the .prom file to write")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="seconds each LVM command may take, since a scan can block on a device that does not answer",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    start = time.monotonic()
    try:
        families = collect(args.timeout)
        success = 1
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as err:
        message = str(err)
        stderr = getattr(err, "stderr", None)
        if stderr:
            message += ": " + stderr.strip()
        print(f"seapath-lvm-textfile: {message}", file=sys.stderr)
        families = []
        success = 0
    families.append(("seapath_lvm_collect_success", "1 when the last collection of the LVM metrics succeeded.", [({}, success)]))
    families.append(
        (
            "seapath_lvm_collect_duration_seconds",
            "Time the last collection of the LVM metrics took.",
            [({}, round(time.monotonic() - start, 3))],
        )
    )
    write_atomically(args.output, render(families))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
