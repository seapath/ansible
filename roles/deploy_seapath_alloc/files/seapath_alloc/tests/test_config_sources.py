# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Tests for where config.py gets its data from: the libvirt domain XML, virsh,
the RBD image metadata, the local profile directory and /etc/seapath/alloc.yaml.
"""

import subprocess

import pytest

from seapath_alloc import config as config_mod
from seapath_alloc.allocator import AllocationStrategy
from seapath_alloc.config import (
    _rbd_source_from_xml,
    _run,
    _vcpu_count_from_xml,
    get_local_profile,
    get_pinning_metadata,
    get_rbd_source,
    get_vcpu_count,
    load_profile,
    load_strategy,
)

DOMAIN_XML = """<domain type='kvm'>
  <name>vm0</name>
  <vcpu placement='static'>4</vcpu>
  <devices>
    <disk type='network' device='disk'>
      <source protocol='rbd' name='rbd/system_vm0'/>
    </disk>
  </devices>
</domain>"""

DOMAIN_XML_CURRENT = """<domain type='kvm'>
  <vcpu placement='static' current='2'>8</vcpu>
</domain>"""


@pytest.fixture
def commands(monkeypatch):
    """Answer _run() from a mapping of first-argument to output."""
    def install(outputs=None, fail=(), error=None):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if error:
                raise error
            key = cmd[1] if len(cmd) > 1 else cmd[0]
            if key in fail:
                return subprocess.CompletedProcess(cmd, 1, stdout="",
                                                   stderr="boom")
            return subprocess.CompletedProcess(
                cmd, 0, stdout=(outputs or {}).get(key, ""), stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        return calls

    return install


# --- _run -----------------------------------------------------------------


def test_run_returns_stdout(commands):
    commands(outputs={"vcpucount": "4\n"})

    assert _run(["virsh", "vcpucount", "vm0"]) == "4\n"


def test_run_returns_none_on_a_failing_command(commands):
    commands(fail=("vcpucount",))

    assert _run(["virsh", "vcpucount", "vm0"]) is None


@pytest.mark.parametrize(
    "error",
    [subprocess.TimeoutExpired("virsh", 5), OSError("no such binary")],
)
def test_run_returns_none_when_the_command_cannot_run(commands, error):
    commands(error=error)

    assert _run(["virsh", "vcpucount", "vm0"]) is None


# --- domain XML parsing ---------------------------------------------------


def test_vcpu_count_from_xml():
    assert _vcpu_count_from_xml(DOMAIN_XML) == 4


def test_vcpu_count_prefers_the_current_attribute():
    """Only `current` vCPU threads exist at start; the rest are hot-pluggable."""
    assert _vcpu_count_from_xml(DOMAIN_XML_CURRENT) == 2


@pytest.mark.parametrize(
    "xml",
    [
        "",
        "<domain><unclosed>",
        "<domain type='kvm'><name>vm0</name></domain>",
        "<domain type='kvm'><vcpu></vcpu></domain>",
        "<domain type='kvm'><vcpu>not a number</vcpu></domain>",
    ],
)
def test_vcpu_count_is_zero_when_the_xml_says_nothing(xml):
    assert _vcpu_count_from_xml(xml) == 0


def test_rbd_source_from_xml():
    assert _rbd_source_from_xml(DOMAIN_XML) == "rbd/system_vm0"


@pytest.mark.parametrize(
    "xml",
    [
        "",
        "<domain><unclosed>",
        "<domain type='kvm'><devices></devices></domain>",
        # A local disk, not RBD.
        "<domain type='kvm'><devices><disk type='file'>"
        "<source file='/var/lib/libvirt/images/vm0.qcow2'/></disk>"
        "</devices></domain>",
        # RBD disk with no name attribute.
        "<domain type='kvm'><devices><disk type='network'>"
        "<source protocol='rbd'/></disk></devices></domain>",
    ],
)
def test_rbd_source_is_empty_when_the_xml_has_no_rbd_disk(xml):
    assert _rbd_source_from_xml(xml) == ""


# --- get_vcpu_count -------------------------------------------------------


def test_vcpu_count_comes_from_the_xml_without_calling_virsh(commands):
    calls = commands()

    assert get_vcpu_count("vm0", domain_xml=DOMAIN_XML) == 4
    assert calls == []


def test_vcpu_count_falls_back_to_virsh(commands):
    calls = commands(outputs={"vcpucount": "6\n"})

    assert get_vcpu_count("vm0") == 6
    assert calls[0][:2] == ["virsh", "vcpucount"]


def test_vcpu_count_falls_back_to_virsh_on_an_unhelpful_xml(commands, caplog):
    commands(outputs={"vcpucount": "6\n"})

    with caplog.at_level("DEBUG", logger=config_mod.log.name):
        assert get_vcpu_count("vm0", domain_xml="<domain/>") == 6

    assert "could not parse vcpu count" in caplog.text


def test_vcpu_count_assumes_one_when_virsh_fails(commands, caplog):
    commands(fail=("vcpucount",))

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        assert get_vcpu_count("vm0") == 1

    assert "assuming 1" in caplog.text


def test_vcpu_count_assumes_one_on_unexpected_virsh_output(commands, caplog):
    commands(outputs={"vcpucount": "error: failed\n"})

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        assert get_vcpu_count("vm0") == 1

    assert "unexpected vcpucount output" in caplog.text


# --- get_rbd_source -------------------------------------------------------


def test_rbd_source_comes_from_the_xml_without_calling_virsh(commands):
    calls = commands()

    assert get_rbd_source("vm0", domain_xml=DOMAIN_XML) == "rbd/system_vm0"
    assert calls == []


def test_rbd_source_falls_back_to_domblklist(commands, caplog):
    commands(outputs={"domblklist":
                      "Type       Device     Target     Source\n"
                      "----------------------------------------\n"
                      "network    disk       vda        rbd/system_vm0\n"})

    with caplog.at_level("DEBUG", logger=config_mod.log.name):
        assert get_rbd_source("vm0", domain_xml="<domain/>") == "rbd/system_vm0"

    assert "no RBD disk found in XML" in caplog.text


def test_rbd_source_skips_the_domblklist_header(commands):
    # The header's fourth token is "Source", which has no slash.
    commands(outputs={"domblklist":
                      "Type       Device     Target     Source\n"
                      "network    disk       vda        rbd/system_vm0\n"})

    assert get_rbd_source("vm0") == "rbd/system_vm0"


def test_rbd_source_ignores_local_disks(commands):
    commands(outputs={"domblklist":
                      "file       disk       vda        /var/lib/vm0.qcow2\n"})

    assert get_rbd_source("vm0") == ""


def test_rbd_source_ignores_short_lines(commands):
    commands(outputs={"domblklist": "\n---\nnetwork disk vda\n"})

    assert get_rbd_source("vm0") == ""


def test_rbd_source_is_empty_when_virsh_fails(commands):
    commands(fail=("domblklist",))

    assert get_rbd_source("vm0") == ""


# --- get_pinning_metadata -------------------------------------------------


def test_pinning_metadata_reads_the_rbd_image_key(commands):
    calls = commands(outputs={"image-meta": "vcpus:\n  isolation: none\n"})

    result = get_pinning_metadata("vm0", domain_xml=DOMAIN_XML)

    assert result == "vcpus:\n  isolation: none"
    assert calls[0] == ["rbd", "image-meta", "get", "rbd/system_vm0",
                        "_seapath_alloc"]


def test_pinning_metadata_is_empty_without_an_rbd_disk(commands, caplog):
    commands(fail=("domblklist",))

    with caplog.at_level("DEBUG", logger=config_mod.log.name):
        assert get_pinning_metadata("vm0") == ""

    assert "no RBD disk found for vm0" in caplog.text


def test_pinning_metadata_is_empty_when_the_key_is_absent(commands, caplog):
    commands(fail=("image-meta",))

    with caplog.at_level("DEBUG", logger=config_mod.log.name):
        assert get_pinning_metadata("vm0", domain_xml=DOMAIN_XML) == ""

    assert "no _seapath_alloc metadata" in caplog.text


# --- get_local_profile ----------------------------------------------------


def test_local_profile_is_read_from_the_profile_directory(tmp_path):
    (tmp_path / "vm0.yaml").write_text("vcpus:\n  isolation: none\n")

    assert get_local_profile("vm0", str(tmp_path)) == "vcpus:\n  isolation: none"


def test_local_profile_is_empty_when_there_is_no_file(tmp_path, caplog):
    with caplog.at_level("DEBUG", logger=config_mod.log.name):
        assert get_local_profile("vm0", str(tmp_path)) == ""

    assert "no local profile at" in caplog.text


def test_local_profile_warns_when_the_file_cannot_be_read(tmp_path, caplog):
    # A directory in place of the file reproduces the OSError.
    (tmp_path / "vm0.yaml").mkdir()

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        assert get_local_profile("vm0", str(tmp_path)) == ""

    assert "cannot read local profile" in caplog.text


# --- load_profile ---------------------------------------------------------


PROFILE_YAML = "vcpus:\n  isolation: exclusive_physical\n  scheduler: FIFO\n"


def test_profile_comes_from_the_rbd_metadata_first(commands, tmp_path, caplog):
    commands(outputs={"image-meta": PROFILE_YAML})

    with caplog.at_level("INFO", logger=config_mod.log.name):
        profile = load_profile("vm0", profile_dir=str(tmp_path),
                               domain_xml=DOMAIN_XML)

    assert profile["vcpus"]["isolation"] == "exclusive_physical"
    assert "loaded pinning profile from RBD metadata" in caplog.text


def test_profile_falls_back_to_the_local_file(commands, tmp_path, caplog):
    commands(fail=("image-meta",))
    (tmp_path / "vm0.yaml").write_text(PROFILE_YAML)

    with caplog.at_level("INFO", logger=config_mod.log.name):
        profile = load_profile("vm0", profile_dir=str(tmp_path),
                               domain_xml=DOMAIN_XML)

    assert profile["vcpus"]["isolation"] == "exclusive_physical"
    assert "loaded pinning profile from" in caplog.text


def test_profile_defaults_to_all_none(commands, tmp_path, caplog):
    commands(fail=("image-meta", "domblklist"))

    with caplog.at_level("INFO", logger=config_mod.log.name):
        profile = load_profile("vm0", profile_dir=str(tmp_path))

    assert profile["vcpus"]["isolation"] == "none"
    assert "running on housekeeping cores" in caplog.text


def test_profile_ignores_invalid_yaml_in_the_rbd_metadata(
    commands, tmp_path, caplog
):
    commands(outputs={"image-meta": "vcpus: [unclosed\n"})

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        profile = load_profile("vm0", profile_dir=str(tmp_path),
                               domain_xml=DOMAIN_XML)

    assert profile["vcpus"]["isolation"] == "none"
    assert "invalid YAML in RBD metadata" in caplog.text


def test_profile_ignores_invalid_yaml_in_the_local_file(
    commands, tmp_path, caplog
):
    commands(fail=("image-meta",))
    (tmp_path / "vm0.yaml").write_text("vcpus: [unclosed\n")

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        profile = load_profile("vm0", profile_dir=str(tmp_path),
                               domain_xml=DOMAIN_XML)

    assert profile["vcpus"]["isolation"] == "none"
    assert "invalid YAML in local profile" in caplog.text


def test_profile_ignores_metadata_that_is_not_a_mapping(
    commands, tmp_path
):
    commands(outputs={"image-meta": "- one\n- two\n"})

    profile = load_profile("vm0", profile_dir=str(tmp_path),
                           domain_xml=DOMAIN_XML)

    assert profile["vcpus"]["isolation"] == "none"


def test_profile_is_all_none_without_pyyaml(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(config_mod, "yaml", None)

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        profile = load_profile("vm0", profile_dir=str(tmp_path))

    assert profile["vcpus"]["isolation"] == "none"
    assert "pyyaml not available" in caplog.text


# --- load_strategy --------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("spreading", AllocationStrategy.SPREADING),
        ("packing", AllocationStrategy.PACKING),
        ("repacking", AllocationStrategy.REPACKING),
        ("REPACKING", AllocationStrategy.REPACKING),
    ],
)
def test_load_strategy_reads_the_settings_file(tmp_path, value, expected):
    settings = tmp_path / "alloc.yaml"
    settings.write_text(f"allocation_strategy: {value}\n")

    assert load_strategy(str(settings)) is expected


def test_load_strategy_defaults_without_a_settings_file(tmp_path):
    assert load_strategy(str(tmp_path / "absent.yaml")) is (
        AllocationStrategy.SPREADING
    )


def test_load_strategy_defaults_when_the_key_is_absent(tmp_path):
    settings = tmp_path / "alloc.yaml"
    settings.write_text("something_else: 1\n")

    assert load_strategy(str(settings)) is AllocationStrategy.SPREADING


def test_load_strategy_defaults_when_the_file_is_not_a_mapping(tmp_path):
    settings = tmp_path / "alloc.yaml"
    settings.write_text("- one\n")

    assert load_strategy(str(settings)) is AllocationStrategy.SPREADING


def test_load_strategy_warns_on_an_unknown_value(tmp_path, caplog):
    settings = tmp_path / "alloc.yaml"
    settings.write_text("allocation_strategy: sideways\n")

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        assert load_strategy(str(settings)) is AllocationStrategy.SPREADING

    assert "unknown allocation_strategy" in caplog.text


def test_load_strategy_warns_when_the_file_cannot_be_parsed(tmp_path, caplog):
    settings = tmp_path / "alloc.yaml"
    settings.write_text("allocation_strategy: [unclosed\n")

    with caplog.at_level("WARNING", logger=config_mod.log.name):
        assert load_strategy(str(settings)) is AllocationStrategy.SPREADING

    assert "could not read allocation_strategy" in caplog.text


def test_load_strategy_defaults_without_pyyaml(monkeypatch, tmp_path):
    monkeypatch.setattr(config_mod, "yaml", None)

    assert load_strategy(str(tmp_path)) is AllocationStrategy.SPREADING


def test_rbd_source_skips_a_network_disk_that_is_not_rbd():
    # An iSCSI or NBD disk is type="network" too, but carries no rbd source.
    xml = ("<domain type='kvm'><devices>"
           "<disk type='network'><source protocol='iscsi' name='t/0'/></disk>"
           "<disk type='network'><source protocol='rbd' name='rbd/system_vm0'/></disk>"
           "</devices></domain>")

    assert _rbd_source_from_xml(xml) == "rbd/system_vm0"


def test_profile_ignores_a_local_file_that_is_not_a_mapping(commands, tmp_path):
    commands(fail=("image-meta",))
    (tmp_path / "vm0.yaml").write_text("- one\n- two\n")

    profile = load_profile("vm0", profile_dir=str(tmp_path),
                           domain_xml=DOMAIN_XML)

    assert profile["vcpus"]["isolation"] == "none"


def test_a_group_that_is_not_a_mapping_falls_back_to_the_defaults(
    commands, tmp_path
):
    # "vcpus: rt" is a plausible typo for a group spec; it must degrade to the
    # built-in defaults rather than blow up the hook.
    commands(outputs={"image-meta": "vcpus: rt\n"})

    profile = load_profile("vm0", profile_dir=str(tmp_path),
                           domain_xml=DOMAIN_XML)

    assert profile["vcpus"]["isolation"] == "none"
    assert profile["vcpus"]["scheduler"] == "OTHER"


def test_config_degrades_gracefully_without_pyyaml():
    """
    python3-yaml is optional on a deployed node; the module has to import
    and fall back to the built-in all-none profile without it.
    """
    import importlib
    import sys

    saved = sys.modules.get("yaml")
    sys.modules["yaml"] = None  # makes "import yaml" raise ImportError
    try:
        reloaded = importlib.reload(config_mod)
        assert reloaded.yaml is None
    finally:
        if saved is None:
            del sys.modules["yaml"]
        else:
            sys.modules["yaml"] = saved
        importlib.reload(config_mod)
