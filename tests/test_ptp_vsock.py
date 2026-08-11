# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/ptp_status_vsock/files/ptp_vsock.py."""

import pytest

from support import load_script

ptp_vsock = load_script("roles/ptp_status_vsock/files/ptp_vsock.py")


class LoopBreak(Exception):
    """Raised from a stub to escape one of the script's infinite loops."""


class FakeConnection:
    def __init__(self, message):
        self.message = message
        self.sent = None
        self.closed = False
        self.recv_size = None

    def recv(self, size):
        self.recv_size = size
        return self.message.encode("utf-8")

    def sendall(self, payload):
        self.sent = payload

    def close(self):
        self.closed = True


class FakeSocket:
    def __init__(self, bind_failures=0):
        self.bind_failures = bind_failures
        self.binds = []
        self.listens = 0
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.exited = True

    def bind(self, address):
        self.binds.append(address)
        if len(self.binds) <= self.bind_failures:
            raise OSError("address already in use")

    def listen(self):
        self.listens += 1


class FakeSocketModule:
    """Stands in for the socket module: AF_VSOCK is Linux-only."""

    AF_VSOCK = 40
    SOCK_STREAM = 1
    VMADDR_CID_HOST = 2
    error = OSError

    def __init__(self, sock):
        self._sock = sock
        self.opened_with = None

    def socket(self, family, kind):
        self.opened_with = (family, kind)
        return self._sock


@pytest.fixture
def ptp_files(tmp_path, monkeypatch):
    """Point the two status file paths at a temporary directory."""
    status = tmp_path / "ptp_state"
    details = tmp_path / "ptp_status"
    monkeypatch.setattr(ptp_vsock, "STATUS_FILE", str(status))
    monkeypatch.setattr(ptp_vsock, "DETAILS_FILE", str(details))
    return status, details


@pytest.fixture
def server(monkeypatch):
    """Install the fake socket module and neutralise the retry sleep."""
    slept = []
    monkeypatch.setattr(ptp_vsock, "sleep", slept.append)

    def install(bind_failures=0):
        sock = FakeSocket(bind_failures)
        module = FakeSocketModule(sock)
        monkeypatch.setattr(ptp_vsock, "socket", module)
        return module, sock, slept

    return install


# --- client handler -------------------------------------------------------


def test_client_handler_returns_the_sync_state(ptp_files):
    status, _ = ptp_files
    status.write_text("1")
    connection = FakeConnection("STATUS")

    ptp_vsock.client_handler(connection)

    assert connection.sent == b"1"


def test_client_handler_returns_the_detailed_status(ptp_files):
    _, details = ptp_files
    details.write_text("offset -12 ns\nfreq +3\n")
    connection = FakeConnection("DETAILS")

    ptp_vsock.client_handler(connection)

    assert connection.sent == b"offset -12 ns\nfreq +3\n"


def test_client_handler_defaults_to_unsynchronised(ptp_files, capsys):
    # The file is missing: the guest must still get an answer.
    connection = FakeConnection("STATUS")

    ptp_vsock.client_handler(connection)

    assert connection.sent == b"0"
    assert "PTP STATUS file not found" in capsys.readouterr().out


def test_client_handler_answers_an_unknown_request(ptp_files, capsys):
    connection = FakeConnection("WHATEVER")

    ptp_vsock.client_handler(connection)

    assert connection.sent == b"0"
    assert "PTP WHATEVER file not found" in capsys.readouterr().out


def test_client_handler_always_closes_the_connection(ptp_files):
    status, _ = ptp_files
    status.write_text("1")
    connection = FakeConnection("STATUS")

    ptp_vsock.client_handler(connection)

    assert connection.closed is True
    assert connection.recv_size == 2048


# --- accept loop ----------------------------------------------------------


def test_accept_connections_hands_the_client_to_a_thread(monkeypatch, capsys):
    connection = FakeConnection("STATUS")
    started = []
    monkeypatch.setattr(
        ptp_vsock, "start_new_thread", lambda fn, args: started.append((fn, args))
    )

    class Listening:
        def accept(self):
            return (connection, (3, 1024))

    ptp_vsock.accept_connections(Listening())

    assert started == [(ptp_vsock.client_handler, (connection,))]
    assert "Connected to: 3:1024" in capsys.readouterr().out


# --- server startup -------------------------------------------------------


def test_start_server_binds_and_listens(server, monkeypatch):
    module, sock, _ = server()
    monkeypatch.setattr(
        ptp_vsock, "accept_connections", lambda s: (_ for _ in ()).throw(LoopBreak)
    )

    with pytest.raises(LoopBreak):
        ptp_vsock.start_server(2, 1234)

    assert module.opened_with == (module.AF_VSOCK, module.SOCK_STREAM)
    assert sock.binds == [(2, 1234)]
    assert sock.listens == 1


def test_start_server_retries_until_the_port_is_free(server, monkeypatch):
    _, sock, slept = server(bind_failures=2)
    monkeypatch.setattr(
        ptp_vsock, "accept_connections", lambda s: (_ for _ in ()).throw(LoopBreak)
    )

    with pytest.raises(LoopBreak):
        ptp_vsock.start_server(2, 1234)

    assert len(sock.binds) == 3
    assert slept == [5, 5]
    assert sock.listens == 1


def test_start_server_serves_connections_in_a_loop(server, monkeypatch, capsys):
    _, sock, _ = server()
    accepted = []

    def accept(s):
        accepted.append(s)
        if len(accepted) == 3:
            raise LoopBreak

    monkeypatch.setattr(ptp_vsock, "accept_connections", accept)

    with pytest.raises(LoopBreak):
        ptp_vsock.start_server(2, 1234)

    assert accepted == [sock, sock, sock]
    assert "Server is listing on the port 1234..." in capsys.readouterr().out


def test_main_serves_the_port_given_on_the_command_line(server, monkeypatch):
    module, sock, _ = server()
    monkeypatch.setattr(
        ptp_vsock, "accept_connections", lambda s: (_ for _ in ()).throw(LoopBreak)
    )

    with pytest.raises(LoopBreak):
        ptp_vsock.main(["1234"])

    assert sock.binds == [(module.VMADDR_CID_HOST, 1234)]


def test_main_falls_back_to_sys_argv(server, monkeypatch):
    module, sock, _ = server()
    monkeypatch.setattr(ptp_vsock.sys, "argv", ["ptp_vsock.py", "4321"])
    monkeypatch.setattr(
        ptp_vsock, "accept_connections", lambda s: (_ for _ in ()).throw(LoopBreak)
    )

    with pytest.raises(LoopBreak):
        ptp_vsock.main()

    assert sock.binds == [(module.VMADDR_CID_HOST, 4321)]
