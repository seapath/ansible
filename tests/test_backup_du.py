# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/backup_restore/files/scripts/backup_du.py."""

import pytest

from support import load_script

backup_du = load_script("roles/backup_restore/files/scripts/backup_du.py")

# One line per RBD image, in the five-column layout the script splits on:
# NAME PROVISIONED <unit> USED <unit>
RBD_DU = """system_guest0 20 GiB 3 GiB
data_guest0_1 10 GiB 512 MiB
system_guest1 20 GiB 1 GiB
"""


@pytest.fixture
def fake_rbd_du(monkeypatch):
    def install(output):
        recorded = {}

        def check_output(cmd, **kwargs):
            recorded["cmd"] = cmd
            recorded["kwargs"] = kwargs
            return output

        monkeypatch.setattr(backup_du, "check_output", check_output)
        return recorded

    return install


def du(include_vm='""', exclude_vm='""'):
    return {"include_vm": include_vm, "exclude_vm": exclude_vm}


@pytest.mark.parametrize(
    "nb,unit,expected",
    [
        (1, "GiB", 1024 * 1024 * 1024),
        (1, "MiB", 1024 * 1024),
        (1, "KiB", 1024),
        (2.5, "MiB", int(2.5 * 1024 * 1024)),
        (1, "gib", 1024 * 1024 * 1024),
        (1, "TiB", 0),
        (1, "B", 0),
    ],
)
def test_convert_size(nb, unit, expected):
    assert backup_du.convert_size(nb, unit) == expected


def test_convert_size_rounds_to_the_nearest_byte():
    # 0.0000000001 GiB is 0.107 byte, which rounds down to zero.
    assert backup_du.convert_size(0.0000000001, "GiB") == 0
    # 0.5 KiB is 512 bytes exactly, no rounding involved.
    assert backup_du.convert_size(0.5, "KiB") == 512


def test_convert_mo_rounds_half_up():
    assert backup_du.convert_mo(1_000_000) == 1
    assert backup_du.convert_mo(1_500_000) == 2
    assert backup_du.convert_mo(1_400_000) == 1
    assert backup_du.convert_mo(0) == 0


def test_pr_lig_formats_name_and_size(capsys):
    backup_du.pr_lig("guest0", 42, " MB")

    assert capsys.readouterr().out == "guest0                       42 MB\n"


def test_pr_table_lists_every_guest_then_the_total(capsys):
    backup_du.pr_table({"guest0": 3000, "guest1": 1000})

    out = capsys.readouterr().out
    assert "guest0" in out
    assert "guest1" in out
    assert "TOTAL :" in out
    assert "4000 MB" in out


def test_pr_table_converts_the_total_to_gigabytes(capsys):
    backup_du.pr_table({"guest0": 1500})

    out = capsys.readouterr().out
    assert "Estimating En GB" in out
    assert "2 GB" in out


def test_pr_table_of_an_empty_mapping_totals_zero(capsys):
    backup_du.pr_table({})

    out = capsys.readouterr().out
    assert "0 MB" in out
    assert "0 GB" in out


@pytest.mark.parametrize(
    "name,expected",
    [
        ("system_guest0", "guest0"),
        ("data_guest0_1", "guest0"),
        ("data_guest0_12", "guest0"),
        ("data_my_guest_3", "my_guest"),
        ("system_guest0@snap1", "guest0"),
        ("data_guest0_1@snap1", "guest0"),
        ("rbd_other", None),
        ("", None),
    ],
)
def test_image_to_guest(name, expected):
    assert backup_du.image_to_guest(name) == expected


def test_read_du_rbd_sums_system_and_data_disks_per_guest(fake_rbd_du):
    fake_rbd_du(RBD_DU)

    volume = backup_du.read_du_rbd(du())

    # 3 GiB is 3221 MB, 512 MiB is 537 MB.
    assert volume == {"guest0": 3221 + 537, "guest1": 1074}


def test_read_du_rbd_selects_the_system_and_data_images(fake_rbd_du):
    recorded = fake_rbd_du(RBD_DU)

    backup_du.read_du_rbd(du())

    assert recorded["cmd"] == (
        '/usr/bin/rbd du 2>/dev/null | grep -E "^(system|data)_"'
    )
    assert recorded["kwargs"]["shell"] is True


def test_read_du_rbd_keeps_only_the_included_guests(fake_rbd_du):
    fake_rbd_du(RBD_DU)

    volume = backup_du.read_du_rbd(du(include_vm='"guest1"'))

    assert list(volume) == ["guest1"]


def test_read_du_rbd_drops_the_excluded_guests(fake_rbd_du):
    fake_rbd_du(RBD_DU)

    volume = backup_du.read_du_rbd(du(exclude_vm='"guest0"'))

    assert list(volume) == ["guest1"]


def test_read_du_rbd_treats_an_empty_include_as_everything(fake_rbd_du):
    fake_rbd_du(RBD_DU)

    volume = backup_du.read_du_rbd(du(include_vm=""))

    assert sorted(volume) == ["guest0", "guest1"]


def test_read_du_rbd_skips_images_that_map_to_no_guest(fake_rbd_du):
    fake_rbd_du("systemd_thing 1 GiB 1 GiB\nsystem_guest0 20 GiB 1 GiB\n")

    volume = backup_du.read_du_rbd(du())

    assert list(volume) == ["guest0"]


def test_read_du_rbd_ignores_blank_lines(fake_rbd_du):
    fake_rbd_du("\n\nsystem_guest0 20 GiB 1 GiB\n\n")

    volume = backup_du.read_du_rbd(du())

    assert volume == {"guest0": 1074}


def test_compute_reads_its_filters_from_the_command_line(
    fake_rbd_du, monkeypatch, capsys
):
    fake_rbd_du(RBD_DU)
    monkeypatch.setattr(backup_du.sys, "argv", ["backup_du.py", '"guest1"', '""'])

    backup_du.compute()

    out = capsys.readouterr().out
    assert "guest1" in out
    assert "guest0" not in out
    assert "TOTAL :" in out
