# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/snmp/files/snmp_getdata.py."""

import io
import json

import pytest

from support import load_script

snmp = load_script("roles/snmp/files/snmp_getdata.py")

CRM_XML = """<crm_mon>
  <summary><stack type="corosync"/></summary>
  <nodes><node name="hyp1" online="true"/></nodes>
</crm_mon>"""


class FakeCommands:
    """Answer run_command() from substring rules, recording what was asked."""

    def __init__(self, rules=(), default="line one\nline two\n"):
        self.rules = list(rules)
        self.default = default
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        for needle, response in self.rules:
            if needle in command:
                return response
        return self.default

    def asked(self, needle):
        return [c for c in self.commands if needle in c]


def raid_rules(temperature="41\n", warnings="0\n", total="0\n",
               devices="Present\n", per_device="0\n"):
    """
    Rules for the five arcconf calls collect_raid() makes.

    They are ordered most specific first: all five share the "GETCONFIG 1"
    prefix and three of them grep for the same S.M.A.R.T. string.
    """
    return [
        ("sum +=", total),
        ("GETCONFIG 1 PD 0", per_device),
        ("GETCONFIG 1 AR", devices),
        ("Current Temperature", temperature),
        ("GETCONFIG 1  |", warnings),
    ]


def monoline_rules(smart_failures="0\n", lvs_sumup=""):
    """Rules for the two collect_monolines() calls that steer disk status."""
    return [
        ("wc -l", smart_failures),
        ("select( .lv_health_status", lvs_sumup),
    ]


@pytest.fixture
def out(monkeypatch):
    """Capture everything the script writes to its output stream."""
    sink = io.StringIO()
    monkeypatch.setattr(snmp, "f", sink)
    return sink


@pytest.fixture
def commands(monkeypatch):
    def install(rules=(), default="line one\nline two\n"):
        fake = FakeCommands(rules, default)
        monkeypatch.setattr(snmp, "run_command", fake)
        return fake

    return install


@pytest.fixture
def status():
    return snmp.DiskStatus()


def oids(sink):
    """Parse the written "oid:value" lines back into a mapping."""
    parsed = {}
    for line in sink.getvalue().splitlines():
        oid, _, value = line.partition(":")
        parsed[oid] = value
    return parsed


# --- primitives -----------------------------------------------------------


def test_run_command_decodes_the_shell_output(monkeypatch):
    recorded = {}

    def check_output(command, **kwargs):
        recorded.update(kwargs, command=command)
        return b"output\n"

    monkeypatch.setattr(snmp.subprocess, "check_output", check_output)

    assert snmp.run_command("echo output") == "output\n"
    assert recorded["shell"] is True
    assert recorded["executable"] == "/bin/bash"


def test_writeline_joins_the_oid_and_the_value(out):
    snmp.writeline(".1.2", "a value")

    assert out.getvalue() == ".1.2:a value\n"


def test_singlelinetooid_trims_and_suffixes_the_oid(out):
    snmp.singlelinetooid(".2.1", "a title", "   PASSED  ")

    assert out.getvalue() == ".2.1.0:PASSED\n"


def test_multilinetooid_numbers_the_lines_from_one(out):
    snmp.multilinetooid(".1.1", "a title", "  first\nsecond  \n")

    assert oids(out) == {".1.1.1": "first", ".1.1.2": "second", ".1.1.0": "2"}


def test_multilinetooid_records_a_zero_count_for_no_output(out):
    snmp.multilinetooid(".1.1", "a title", "")

    assert oids(out) == {".1.1.0": "0"}


def test_dictarrayoid_writes_the_column_names_then_the_rows(out):
    rows = [
        {"lv_name": "root", "lv_health_status": ""},
        {"lv_name": "data", "lv_health_status": "partial"},
    ]

    snmp.dictarrayoid(".2.5", "a title", rows)

    assert oids(out) == {
        # The first row only names the columns.
        ".2.5.0.0": "lv_name",
        ".2.5.0.1": "lv_health_status",
        ".2.5.1.0": "data",
        ".2.5.1.1": "partial",
    }


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/dev/null", True),
        ("/etc/hosts", False),
        ("/dev/there-is-no-such-device", False),
    ],
)
def test_exist_and_is_character(path, expected):
    assert snmp.exist_and_is_character(path) is expected


def test_disk_status_starts_clean(status):
    assert status.globalreplacedisk == "OK"
    assert status.replacedisk == ["OK", "OK", "OK", "OK"]


# --- IPMI -----------------------------------------------------------------


def test_collect_ipmi_does_nothing_without_a_bmc(out, commands, monkeypatch):
    fake = commands()
    monkeypatch.setattr(snmp, "exist_and_is_character", lambda path: False)

    snmp.collect_ipmi()

    assert fake.commands == []
    assert out.getvalue() == ""


@pytest.mark.parametrize(
    "device", ["/dev/ipmi0", "/dev/ipmi/0", "/dev/ipmidev/0"]
)
def test_collect_ipmi_accepts_any_of_the_bmc_device_names(
    out, commands, monkeypatch, device
):
    commands()
    monkeypatch.setattr(snmp, "exist_and_is_character", lambda path: path == device)

    snmp.collect_ipmi()

    assert oids(out)[".4.1.0"] == "2"


def test_collect_ipmi_reads_the_four_sensor_views(out, commands, monkeypatch):
    fake = commands()
    monkeypatch.setattr(snmp, "exist_and_is_character", lambda path: True)

    snmp.collect_ipmi()

    assert len(fake.asked("ipmitool")) == 4
    assert fake.asked("sensor | ")
    assert fake.asked("sensor -v")
    assert fake.asked("sdr list | ")
    assert fake.asked("sdr list -v")
    assert set(oids(out)) >= {".4.1.0", ".4.2.0", ".4.3.0", ".4.4.0"}


# --- RAID -----------------------------------------------------------------


@pytest.fixture
def with_arcconf(monkeypatch):
    def install(present=True):
        monkeypatch.setattr(snmp.os.path, "isfile", lambda path: present)

    return install


def test_collect_raid_does_nothing_without_a_controller(
    out, commands, with_arcconf, status
):
    fake = commands()
    with_arcconf(False)

    snmp.collect_raid(status)

    assert fake.commands == []
    assert out.getvalue() == ""


def test_collect_raid_records_the_disk_temperatures(
    out, commands, with_arcconf, status
):
    commands(rules=raid_rules(temperature="41\n 42 \n"))
    with_arcconf()

    snmp.collect_raid(status)

    written = oids(out)
    assert written[".3.1.1.0"] == "41"
    assert written[".3.1.2.0"] == "42"


def test_collect_raid_leaves_healthy_disks_alone(
    out, commands, with_arcconf, status
):
    commands(rules=raid_rules(warnings="0\n0\n", devices="Present\nPresent\n"))
    with_arcconf()

    snmp.collect_raid(status)

    assert status.replacedisk == ["OK", "OK", "OK", "OK"]
    assert status.globalreplacedisk == "OK"


def test_collect_raid_flags_the_disk_that_raised_smart_warnings(
    out, commands, with_arcconf, status
):
    commands(rules=raid_rules(warnings="0\n3\n", devices="Present\nPresent\n"))
    with_arcconf()

    snmp.collect_raid(status)

    assert status.replacedisk[1] == "RAID SMART Warnings on disk2"
    assert status.globalreplacedisk == "RAID SMART Warnings on one disk"


@pytest.mark.parametrize(
    "total,expected",
    [
        ("0\n", "OK"),
        ("\n", "OK"),
        ("5\n", "RAID SMART Warnings on one disk"),
    ],
)
def test_collect_raid_reads_the_total_smart_warning_count(
    out, commands, with_arcconf, status, total, expected
):
    commands(rules=raid_rules(total=total))
    with_arcconf()

    snmp.collect_raid(status)

    assert status.globalreplacedisk == expected


def test_collect_raid_flags_a_missing_array_device(
    out, commands, with_arcconf, status
):
    commands(rules=raid_rules(devices="Present\nMissing\n"))
    with_arcconf()

    snmp.collect_raid(status)

    assert status.replacedisk[1] == 1


@pytest.mark.parametrize("warnings,flagged", [("0\n", False), ("2\n", True),
                                              ("\n", False)])
def test_collect_raid_checks_each_physical_device(
    out, commands, with_arcconf, status, warnings, flagged
):
    commands(rules=raid_rules(per_device=warnings))
    with_arcconf()

    snmp.collect_raid(status)

    assert (status.replacedisk == [1, 1, 1, 1]) is flagged
    assert oids(out)[".3.5.1.1.0"] == warnings.strip()


# --- SMART health ---------------------------------------------------------


def test_collect_smart_health_probes_the_four_sata_disks(out, commands, status):
    fake = commands(default="PASSED\n")

    snmp.collect_smart_health(status)

    assert len(fake.asked("smartctl -H /dev/sd")) == 4
    assert set(oids(out)) == {".2.1.0", ".2.2.0", ".2.3.0", ".2.4.0"}
    assert status.replacedisk == ["OK", "OK", "OK", "OK"]


def test_collect_smart_health_flags_a_disk_that_did_not_pass(
    out, commands, status
):
    commands(rules=[("/dev/sdb", "FAILED!\n")], default="PASSED\n")

    snmp.collect_smart_health(status)

    assert status.replacedisk == ["OK", 1, "OK", "OK"]


def test_collect_smart_health_ignores_a_disk_that_is_not_there(
    out, commands, status
):
    # An absent disk produces no output at all, which is not a failure.
    commands(default="\n")

    snmp.collect_smart_health(status)

    assert status.replacedisk == ["OK", "OK", "OK", "OK"]
    assert oids(out)[".2.1.0"] == ""


# --- LVM ------------------------------------------------------------------


def test_collect_lvs_writes_the_logical_volume_table(out, commands):
    commands(default=json.dumps([
        {"lv_name": "root", "lv_health_status": ""},
        {"lv_name": "data", "lv_health_status": "partial"},
    ]))

    snmp.collect_lvs()

    written = oids(out)
    assert written[".2.5.0.0"] == "lv_name"
    assert written[".2.5.1.1"] == "partial"


# --- monoline values ------------------------------------------------------


def test_collect_monolines_writes_one_value_per_oid(out, commands, status):
    commands(rules=monoline_rules(), default="value\n")

    snmp.collect_monolines(status)

    assert set(oids(out)) == {".2.6.0", ".2.7.0", ".2.8.0", ".2.9.0", ".2.10.0"}


def test_collect_monolines_reports_healthy_smart_disks(out, commands, status):
    commands(rules=monoline_rules(), default="value\n")

    snmp.collect_monolines(status)

    assert oids(out)[".2.6.0"] == "SMARTOK"
    assert status.globalreplacedisk == "OK"


def test_collect_monolines_reports_failing_smart_disks(out, commands, status):
    commands(rules=monoline_rules(smart_failures="2\n"), default="value\n")

    snmp.collect_monolines(status)

    assert oids(out)[".2.6.0"] == "SMARTPROBLEM"
    assert status.globalreplacedisk == "SMART tests not passed"


def test_collect_monolines_reports_a_clean_lvm(out, commands, status):
    commands(rules=monoline_rules(), default="value\n")

    snmp.collect_monolines(status)

    assert oids(out)[".2.9.0"] == "NO LVS PROBLEM"
    assert status.globalreplacedisk == "OK"


def test_collect_monolines_reports_an_unhealthy_lvm(out, commands, status):
    commands(rules=monoline_rules(lvs_sumup='{"lv_name":"data"}'),
             default="value\n")

    snmp.collect_monolines(status)

    assert oids(out)[".2.9.0"] == 'LVS PROBLEM: {"lv_name":"data"}'
    assert status.globalreplacedisk == "LVS health not OK"


def test_collect_monolines_reads_the_ceph_health(out, commands, status):
    fake = commands(rules=monoline_rules() + [("health.status", "HEALTH_OK\n")],
                    default="value\n")

    snmp.collect_monolines(status)

    assert fake.asked("ceph status --format json-pretty")
    assert oids(out)[".2.10.0"] == "HEALTH_OK"


# --- multiline values -----------------------------------------------------


def test_collect_multilines_writes_every_section(out, commands):
    commands(rules=[("crm status --as-xml", CRM_XML)])

    snmp.collect_multilines()

    written = oids(out)
    # .1.1 to .1.10 are plain multiline dumps; .1.11 is replaced by the two
    # parsed crm sub-trees.
    for i in range(1, 11):
        assert ".1.{}.0".format(i) in written
    assert ".1.11.0" not in written


def test_collect_multilines_runs_the_expected_tools(out, commands):
    fake = commands(rules=[("crm status --as-xml", CRM_XML)])

    snmp.collect_multilines()

    assert fake.asked("crm status")
    assert fake.asked("virsh --connect qemu:///system domstats")
    assert fake.asked("dommemstat")
    assert fake.asked("ceph status")
    assert fake.asked("virt-df.sh")
    assert fake.asked("virsh -c qemu:///system list --all")
    assert fake.asked("Temperature_Celsius")
    assert fake.asked("udevadm")
    assert fake.asked("lvs -a -o +devices,lv_health_status")


def test_collect_multilines_splits_the_crm_status_into_summary_and_nodes(
    out, commands
):
    commands(rules=[("crm status --as-xml", CRM_XML)])

    snmp.collect_multilines()

    written = oids(out)
    assert json.loads(written[".1.11.0.1.1"]) == {"stack": {"type": "corosync"}}
    assert json.loads(written[".1.11.0.2.1"]) == {
        "node": {"name": "hyp1", "online": "true"}
    }


def test_collect_multilines_survives_an_unparsable_crm_status(out, commands):
    commands(rules=[("crm status --as-xml", "<crm_mon><unclosed>"),
                    ("lvs -a -o +devices,lv_health_status", "lvs output\n")])

    snmp.collect_multilines()

    written = oids(out)
    assert ".1.11.0.1.1" not in written
    # The raw crm output is reported instead of the parsed sub-trees, and in
    # particular instead of the lvs status the previous iteration produced.
    assert written[".1.11.1"] == "<crm_mon><unclosed>"
    assert written[".1.10.1"] == "lvs output"


# --- disk replacement summary ---------------------------------------------


def test_write_disk_replacement_status_reports_healthy_disks(out, status):
    snmp.write_disk_replacement_status(status)

    written = oids(out)
    assert [written[".5.{}.0".format(i)] for i in range(1, 5)] == ["OK"] * 4
    assert written[".5.5.0"] == "OK"


def test_write_disk_replacement_status_keeps_the_raid_message(out, status):
    status.replacedisk[0] = "RAID SMART Warnings on disk1"
    status.globalreplacedisk = "RAID SMART Warnings on one disk"

    snmp.write_disk_replacement_status(status)

    written = oids(out)
    assert written[".5.1.0"] == "RAID SMART Warnings on disk1"
    assert written[".5.5.0"] == "RAID SMART Warnings on one disk"


def test_write_disk_replacement_status_reports_a_flagged_disk(out, status):
    # The SMART and array-device checks flag a disk with the integer 1, where
    # the RAID check stores a message; both have to reach the OID tree.
    status.replacedisk[2] = 1

    snmp.write_disk_replacement_status(status)

    written = oids(out)
    assert written[".5.3.0"] == "1"
    assert written[".5.1.0"] == "OK"
    assert written[".5.5.0"] == "Problem on one disk"


def test_a_failing_disk_still_gets_published(out, commands, status):
    # The whole point of the collector: a disk going bad must be reported,
    # not crash the run and leave snmpd on the last healthy snapshot.
    commands(rules=[("/dev/sdc", "FAILED!\n")], default="PASSED\n")

    snmp.collect_smart_health(status)
    snmp.write_disk_replacement_status(status)

    written = oids(out)
    assert written[".2.3.0"] == "FAILED!"
    assert written[".5.3.0"] == "1"
    assert written[".5.5.0"] == "Problem on one disk"


# --- entry point ----------------------------------------------------------


def test_main_publishes_the_data_file_atomically(
    monkeypatch, commands, with_arcconf, tmp_path
):
    commands(rules=[("crm status --as-xml", CRM_XML),
                    ("jq -c .report[].lv", json.dumps([{"lv_name": "root"}]))]
                   + monoline_rules(),
             default="PASSED\n")
    with_arcconf(False)
    monkeypatch.setattr(snmp, "exist_and_is_character", lambda path: False)
    tmp_file = tmp_path / "snmpdata_tmp.txt"
    final = tmp_path / "snmpdata.txt"
    monkeypatch.setattr(snmp, "snmpdata_tmp", str(tmp_file))
    monkeypatch.setattr(snmp, "snmpdata", str(final))

    snmp.main()

    # The collector writes to a temporary file and renames it into place, so
    # snmpd never reads a half-written table.
    assert not tmp_file.exists()
    assert final.read_text().startswith(".2.1.0:PASSED")
    assert ".5.5.0:OK" in final.read_text()
