# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/configure_libvirt/files/seapath-tap-link-speed."""

import io
import socket

import pytest

from support import load_script

hook = load_script(
    "roles/configure_libvirt/files/seapath-tap-link-speed", "tap_link_speed"
)

DOMAIN = """
<domain>
  <name>vm0</name>
  <devices>
    <interface type="bridge"><target dev="vnet0"/></interface>
    <interface type="direct"><target dev="macvtap0"/></interface>
    <interface type="bridge"><target/></interface>
    <interface type="hostdev"/>
    <interface type="bridge"><target dev="vnet1"/></interface>
  </devices>
</domain>
"""


@pytest.fixture
def logs(monkeypatch):
    records = []
    monkeypatch.setattr(
        hook.syslog, "syslog", lambda priority, msg: records.append((priority, msg))
    )
    return records


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "tap-link-speed.conf"
    path.write_text("# managed by Ansible\n\n1000\n", encoding="utf-8")
    monkeypatch.setattr(hook, "CONFIG_FILE", str(path))
    return path


@pytest.fixture
def sys_class_net(tmp_path, monkeypatch):
    root = tmp_path / "net"
    for dev in ("vnet0", "vnet1"):
        (root / dev).mkdir(parents=True)
        (root / dev / "tun_flags").write_text("0x1002\n", encoding="utf-8")
    (root / "macvtap0").mkdir()
    monkeypatch.setattr(hook, "SYS_CLASS_NET", str(root))
    return root


class FakeSocket:
    def __init__(self, *args):
        self.args = args
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True

    def fileno(self):
        return 42


class FakeEthtool:
    """Answers GSET like the tun driver and records each SSET."""

    def __init__(self, fail_on=()):
        self.fail_on = fail_on
        self.sets = {}

    def __call__(self, sock, dev, data):
        fields = list(hook.ETHTOOL_CMD.unpack(data.tobytes()))
        if dev in self.fail_on:
            raise OSError(95, "Operation not supported")
        if fields[0] == hook.ETHTOOL_GSET:
            fields = [hook.ETHTOOL_GSET, 0x1, 0x2, 10, 1, 7, 0, 0, 1, 0, 0, 0, 0,
                      0, 0, 0x4, 0, 0]
            data[:] = type(data)("B", hook.ETHTOOL_CMD.pack(*fields))
        else:
            self.sets[dev] = fields


def test_read_speed_skips_comments_and_blank_lines(config):
    assert hook.read_speed() == 1000


@pytest.mark.parametrize("content", ["# nothing\n", "0\n", "4294967296\n"])
def test_read_speed_rejects_missing_or_out_of_range(config, content):
    config.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        hook.read_speed()


def test_read_speed_rejects_garbage(config):
    config.write_text("fast\n", encoding="utf-8")
    with pytest.raises(ValueError):
        hook.read_speed()


def test_tap_devices_lists_targets_with_a_dev():
    assert hook.tap_devices(DOMAIN) == ["vnet0", "macvtap0", "vnet1"]


def test_is_tap_needs_tun_flags(sys_class_net):
    assert hook.is_tap("vnet0")
    assert not hook.is_tap("macvtap0")
    assert not hook.is_tap("missing0")


def test_ethtool_passes_the_buffer_address(monkeypatch):
    calls = []
    monkeypatch.setattr(
        hook.fcntl, "ioctl", lambda fd, request, arg: calls.append((fd, request, arg))
    )
    data = hook.array.array("B", bytes(hook.ETHTOOL_CMD.size))
    hook._ethtool(FakeSocket(), "vnet0", data)
    fd, request, ifreq = calls[0]
    assert (fd, request) == (42, hook.SIOCETHTOOL)
    assert len(ifreq) == hook.IFREQ_SIZE
    name, address = hook.IFREQ.unpack(ifreq[: hook.IFREQ.size])
    assert name.rstrip(b"\0") == b"vnet0"
    assert address == data.buffer_info()[0]


@pytest.mark.parametrize("speed, low, high", [(1000, 1000, 0), (100000, 34464, 1)])
def test_set_speed_keeps_the_other_fields(monkeypatch, speed, low, high):
    ethtool = FakeEthtool()
    monkeypatch.setattr(hook, "_ethtool", ethtool)
    hook.set_speed(FakeSocket(), "vnet0", speed)
    fields = ethtool.sets["vnet0"]
    assert fields[0] == hook.ETHTOOL_SSET
    assert (fields[hook.SPEED], fields[hook.SPEED_HI]) == (low, high)
    assert fields[hook.DUPLEX] == hook.DUPLEX_FULL
    assert fields[hook.AUTONEG] == hook.AUTONEG_DISABLE
    # supported, advertising, port and lp_advertising come from GSET.
    assert fields[1:3] == [0x1, 0x2]
    assert fields[5] == 7
    assert fields[15] == 0x4


@pytest.mark.parametrize(
    "argv",
    [["hook"], ["hook", "vm0", "prepare", "begin", "-"], ["hook", "vm0", "stopped"]],
)
def test_run_ignores_other_operations(monkeypatch, argv):
    monkeypatch.setattr(hook, "read_speed", pytest.fail)
    hook.run(argv, io.StringIO(DOMAIN))


def test_run_sets_every_tap(monkeypatch, config, sys_class_net, logs):
    ethtool = FakeEthtool(fail_on=("vnet1",))
    monkeypatch.setattr(hook, "_ethtool", ethtool)
    sockets = []

    def open_socket(*args):
        sockets.append(FakeSocket(*args))
        return sockets[-1]

    hook.run(["hook", "vm0", "started", "begin", "-"], io.StringIO(DOMAIN), open_socket)
    assert list(ethtool.sets) == ["vnet0"]
    assert sockets[0].args == (socket.AF_INET, socket.SOCK_DGRAM)
    assert sockets[0].closed
    assert logs == [
        (hook.syslog.LOG_INFO, "vm0: vnet0 reports 1000 Mb/s"),
        (
            hook.syslog.LOG_ERR,
            "vm0: cannot set the speed of vnet1: [Errno 95] Operation not supported",
        ),
    ]


def test_run_without_tap_opens_no_socket(config, sys_class_net, logs):
    domain = "<domain><devices><interface><target dev='macvtap0'/></interface></devices></domain>"
    hook.run(["hook", "vm0", "started"], io.StringIO(domain), pytest.fail)
    assert logs == []


def test_run_logs_a_missing_config(tmp_path, monkeypatch, logs):
    monkeypatch.setattr(hook, "CONFIG_FILE", str(tmp_path / "missing"))
    hook.run(["hook", "vm0", "started"], io.StringIO(DOMAIN), pytest.fail)
    assert logs[0][0] == hook.syslog.LOG_ERR
    assert logs[0][1].startswith("vm0: [Errno 2]")


def test_run_logs_invalid_xml(config, logs):
    hook.run(["hook", "vm0", "started"], io.StringIO("<domain>"), pytest.fail)
    assert logs[0][0] == hook.syslog.LOG_ERR


def test_main_always_exits_0(monkeypatch, logs):
    opened = []
    monkeypatch.setattr(hook.syslog, "openlog", opened.append)

    def boom(argv, stdin):
        raise RuntimeError("boom")

    monkeypatch.setattr(hook, "run", boom)
    assert hook.main() == 0
    assert opened == ["seapath-tap-link-speed"]
    assert logs == [(hook.syslog.LOG_ERR, "unexpected error: RuntimeError('boom')")]


def test_main_runs_the_hook(monkeypatch):
    monkeypatch.setattr(hook.syslog, "openlog", lambda ident: None)
    seen = []
    monkeypatch.setattr(hook, "run", lambda argv, stdin: seen.append(argv))
    assert hook.main() == 0
    assert seen == [hook.sys.argv]
