# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/deploy_containers_cluster/files/seapath-container-handover."""

import subprocess

import pytest

from support import load_script

handover = load_script(
    "roles/deploy_containers_cluster/files/seapath-container-handover",
    "seapath_container_handover",
)

GATE = ["web.0", "processbus"]
PORTS = ["web0", "web0b"]
UNITS = ["web-rt.service", "web-rt-b.service"]
SIDES = {handover.cookie("web.0", side): side for side in (handover.CONTAINER, handover.STANDIN)}


class Host:
    """
    systemd and Open vSwitch as the script sees them.

    ``active`` is the set of running units, ``closed`` the port each side of
    the gate has closed, ``events`` what happened in order. ``fail_start``
    names the units that do not start, ``dies`` one that stops by itself
    during a wait, ``ofctl_fails`` makes every ovs-ofctl call fail.
    """

    def __init__(self, active):
        self.active = set(active)
        self.closed = {}
        self.events = []
        self.fail_start = set()
        self.dies = None
        self.ofctl_fails = False

    def run(self, argv, check=False, text=None, input=None, stdout=None):
        if argv[0] == "systemctl":
            code, out = self.systemctl(argv), None
        else:
            code, out = self.ofctl(argv, input)
        if check and code:
            raise subprocess.CalledProcessError(code, argv)
        return subprocess.CompletedProcess(argv, code, stdout=out)

    def systemctl(self, argv):
        verb, unit = argv[1], argv[-1]
        if verb == "is-active":
            return 0 if unit in self.active else 3
        self.events.append(f"{verb} {unit}")
        if verb == "start":
            if unit in self.fail_start:
                return 1
            self.active.add(unit)
        else:
            self.active.discard(unit)
        return 0

    @staticmethod
    def side_of(text):
        return SIDES[text.split("cookie=")[1].split("/")[0].split(",")[0]]

    def add(self, rule):
        assert ",priority=65535,in_port=" in rule and rule.endswith(",actions=drop")
        self.closed[self.side_of(rule)] = rule.split("in_port=")[1].split(",")[0]

    def ofctl(self, argv, rules):
        assert argv[:3] == ["ovs-ofctl", "-O", "OpenFlow14"]
        if self.ofctl_fails:
            return 1, None
        if argv[3] == "dump-flows":
            assert argv[4] == "processbus" and argv[5].endswith("/-1")
            side = self.side_of(argv[5])
            return 0, "OFPST_FLOW reply:\n" + (" in_port=7 actions=drop\n" if side in self.closed else "")
        if argv[3] == "del-flows":
            assert argv[4] == "processbus" and argv[5].endswith("/-1")
            self.closed.pop(self.side_of(argv[5]), None)
        elif argv[3] == "add-flow":
            assert argv[4] == "processbus"
            self.add(argv[5])
            self.events.append(f"closed {sorted(self.closed.values())}")
        else:
            assert argv[3:] == ["--bundle", "add-flows", "processbus", "-"]
            opened, closed = rules.splitlines()
            assert opened.startswith("delete cookie=") and opened.endswith("/-1")
            assert closed.startswith("add cookie=")
            self.closed.pop(self.side_of(opened), None)
            self.add(closed[len("add "):])
            self.events.append(f"swapped, closed {sorted(self.closed.values())}")
        return 0, None

    def sleep(self, seconds):
        self.events.append(f"sleep {seconds:g}")
        if self.dies:
            self.active.discard(self.dies)


@pytest.fixture
def host(monkeypatch):
    def make(active, closed=None):
        made = Host(active)
        made.closed = dict(closed or {})
        monkeypatch.setattr(handover.subprocess, "run", made.run)
        monkeypatch.setattr(handover.time, "sleep", made.sleep)
        return made

    return make


def enter(settle=None):
    argv = ["enter", *GATE, *PORTS, *UNITS]
    return handover.main(argv + (["--settle", str(settle)] if settle is not None else []))


def leave(settle=None):
    argv = ["leave", *GATE, *PORTS, *UNITS]
    return handover.main(argv + (["--settle", str(settle)] if settle is not None else []))


def test_cookies_are_stable_and_proper_to_the_gate_and_the_side():
    cookies = {handover.cookie(gate, side) for gate in ("web.0", "web.1")
               for side in (handover.CONTAINER, handover.STANDIN)}
    assert len(cookies) == 4
    assert handover.cookie("web.0", handover.STANDIN) == handover.cookie("web.0", handover.STANDIN)
    assert all(int(cookie, 16) < 2**64 for cookie in cookies)


def test_guard_closes_the_port_of_a_stand_in_that_starts(host):
    node = host({"web-rt.service"})

    assert handover.main(["guard", *GATE, "web0b"]) == 0

    assert node.closed == {handover.STANDIN: "web0b"}


def test_guard_closes_the_new_port_in_place_of_the_one_it_had(host):
    node = host({"web-rt.service"}, {handover.STANDIN: "gone"})

    assert handover.main(["guard", *GATE, "web0b"]) == 0

    assert node.closed == {handover.STANDIN: "web0b"}


def test_guard_leaves_open_the_port_of_a_stand_in_heard_that_starts_again(host):
    node = host(set(), {handover.CONTAINER: "web0"})

    assert handover.main(["guard", *GATE, "web0b"]) == 0

    assert node.closed == {handover.CONTAINER: "web0"}
    assert node.events == []


def test_enter_starts_the_stand_in_then_swaps_the_ports(host, capsys):
    node = host({"web-rt.service"})
    # what the stand-in's unit does as it starts
    real = node.systemctl

    def systemctl(argv):
        code = real(argv)
        if argv[1] == "start":
            handover.guard("web.0", "processbus", "web0b")
        return code

    node.systemctl = systemctl

    assert enter(settle=2.5) == 0

    assert node.events == [
        "start web-rt-b.service",
        "closed ['web0b']",
        "sleep 1",
        "sleep 1",
        "sleep 0.5",
        "swapped, closed ['web0']",
    ]
    assert node.closed == {handover.CONTAINER: "web0"}
    assert node.active == {"web-rt.service", "web-rt-b.service"}
    assert "web-rt-b.service: heard on web0b, web0 closed" in capsys.readouterr().out


def test_enter_leaves_a_stand_in_already_heard_as_it_is(host, capsys):
    node = host({"web-rt-b.service"})

    assert enter() == 0

    assert node.events == []
    assert "already heard on web0b" in capsys.readouterr().out


def test_enter_needs_the_container_to_run(host, capsys):
    node = host(set())

    assert enter() == 1

    assert node.events == []
    assert "web-rt.service does not run" in capsys.readouterr().err


def test_a_stand_in_that_does_not_start_leaves_the_container_heard(host, capsys):
    node = host({"web-rt.service"}, {handover.STANDIN: "web0b"})
    node.fail_start = {"web-rt-b.service"}

    assert enter() == 1

    assert node.events == ["start web-rt-b.service", "stop web-rt-b.service"]
    assert node.closed == {}
    assert "web-rt.service" in node.active
    assert "did not start or did not stay up, web-rt.service keeps the service" in capsys.readouterr().err


def test_a_stand_in_that_stops_while_settling_leaves_the_container_heard(host):
    node = host({"web-rt.service"}, {handover.STANDIN: "web0b"})
    node.dies = "web-rt-b.service"

    assert enter(settle=10) == 1

    assert node.events == ["start web-rt-b.service", "sleep 1", "stop web-rt-b.service"]
    assert node.closed == {}


def test_leave_swaps_the_ports_back_and_stops_the_stand_in(host, capsys):
    node = host({"web-rt.service", "web-rt-b.service"}, {handover.CONTAINER: "web0"})

    assert leave(settle=1) == 0

    assert node.events == [
        "sleep 1",
        "swapped, closed ['web0b']",
        "stop web-rt-b.service",
    ]
    assert node.active == {"web-rt.service"}
    assert node.closed == {}
    assert "web-rt.service: heard on web0, web0b closed" in capsys.readouterr().out


def test_leave_without_a_stand_in_has_nothing_to_do(host, capsys):
    node = host({"web-rt.service"})

    assert leave() == 0

    assert node.events == []
    assert "does not run, web-rt.service is the one heard" in capsys.readouterr().out


def test_leave_keeps_the_stand_in_heard_while_the_container_does_not_run(host, capsys):
    node = host({"web-rt-b.service"}, {handover.CONTAINER: "web0"})

    assert leave() == 1

    assert node.events == []
    assert node.active == {"web-rt-b.service"}
    assert node.closed == {handover.CONTAINER: "web0"}
    assert "web-rt-b.service keeps the service" in capsys.readouterr().err


def test_leave_keeps_the_stand_in_heard_when_the_container_stops_while_settling(host):
    node = host({"web-rt.service", "web-rt-b.service"}, {handover.CONTAINER: "web0"})
    node.dies = "web-rt.service"

    assert leave(settle=5) == 1

    assert node.events == ["sleep 1"]
    assert node.closed == {handover.CONTAINER: "web0"}
    assert node.active == {"web-rt-b.service"}


def test_reset_opens_the_port_of_a_workload_that_starts_alone(host):
    node = host(set(), {handover.CONTAINER: "gone"})

    assert handover.main(["reset", *GATE, "web0", "web-rt-b.service"]) == 0

    assert node.closed == {}


def test_reset_closes_the_new_port_of_a_workload_restarted_under_a_stand_in(host):
    node = host({"web-rt-b.service"}, {handover.CONTAINER: "gone"})

    assert handover.main(["reset", *GATE, "web0", "web-rt-b.service"]) == 0

    assert node.closed == {handover.CONTAINER: "web0"}


def test_clear_deletes_the_rules_of_the_gate(host):
    node = host(set(), {handover.CONTAINER: "web0", handover.STANDIN: "web0b"})

    assert handover.main(["clear", *GATE]) == 0

    assert node.closed == {}


def test_a_failing_bridge_is_reported(host, capsys):
    node = host({"web-rt.service"})
    node.ofctl_fails = True

    assert handover.main(["guard", *GATE, "web0b"]) == 1

    assert "ovs-ofctl" in capsys.readouterr().err


def test_main_reads_the_command_line(host, monkeypatch):
    node = host(set(), {handover.STANDIN: "web0b"})
    monkeypatch.setattr(handover.sys, "argv", ["seapath-container-handover", "clear", *GATE])

    assert handover.main() == 0

    assert node.closed == {}
