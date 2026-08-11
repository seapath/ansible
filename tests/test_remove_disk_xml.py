# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/backup_restore/files/scripts/remove_disk_xml.py."""

import pytest

from support import load_script

remove_disk_xml = load_script(
    "roles/backup_restore/files/scripts/remove_disk_xml.py"
)

DOMAIN_XML = """<domain type='kvm'>
  <name>guest0</name>
  <devices>
    <disk type='network' device='disk'>
      <source protocol='rbd' name='rbd/system_guest0'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <disk type='network' device='disk'>
      <source protocol='rbd' name='rbd/data_guest0_1'/>
      <target dev='vdb' bus='virtio'/>
    </disk>
    <interface type='bridge'>
      <source bridge='br0'/>
    </interface>
  </devices>
</domain>
"""

DISKLESS_XML = """<domain type='kvm'>
  <name>guest0</name>
  <devices>
    <interface type='bridge'>
      <source bridge='br0'/>
    </interface>
  </devices>
</domain>
"""


@pytest.fixture
def xml_pair(tmp_path):
    def make(content):
        src = tmp_path / "domain.xml"
        src.write_text(content)
        return str(src), str(tmp_path / "domain-nodisk.xml")

    return make


def test_removes_every_disk_element(xml_pair):
    src, dst = xml_pair(DOMAIN_XML)

    remove_disk_xml.remove_disks(src, dst)

    with open(dst) as f:
        written = f.read()
    assert "<disk" not in written


def test_keeps_the_other_devices(xml_pair):
    src, dst = xml_pair(DOMAIN_XML)

    remove_disk_xml.remove_disks(src, dst)

    with open(dst) as f:
        written = f.read()
    assert "<interface" in written
    assert "br0" in written
    assert "<name>guest0</name>" in written


def test_leaves_a_diskless_domain_untouched(xml_pair):
    src, dst = xml_pair(DISKLESS_XML)

    remove_disk_xml.remove_disks(src, dst)

    with open(dst) as f:
        written = f.read()
    assert "<interface" in written
    assert "<disk" not in written


def test_does_not_modify_the_source_file(xml_pair):
    src, dst = xml_pair(DOMAIN_XML)

    remove_disk_xml.remove_disks(src, dst)

    with open(src) as f:
        assert f.read() == DOMAIN_XML


def test_main_reads_source_and_destination_from_its_argv(xml_pair):
    src, dst = xml_pair(DOMAIN_XML)

    remove_disk_xml.main([src, dst])

    with open(dst) as f:
        assert "<disk" not in f.read()


def test_main_falls_back_to_sys_argv(xml_pair, monkeypatch):
    src, dst = xml_pair(DOMAIN_XML)
    monkeypatch.setattr(remove_disk_xml.sys, "argv", ["remove_disk_xml.py", src, dst])

    remove_disk_xml.main()

    with open(dst) as f:
        assert "<disk" not in f.read()
