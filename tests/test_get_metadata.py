# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/backup_restore/files/scripts/get_metadata.py."""

import pytest

from support import install_stub_module, load_script

# rados and rbd are the Ceph C bindings; they only exist on a deployed node.
install_stub_module("rados")
install_stub_module("rbd")

get_metadata = load_script("roles/backup_restore/files/scripts/get_metadata.py")


class FakeImage:
    def __init__(self, ioctx, name, keys=(), error=None):
        self.ioctx = ioctx
        self.name = name
        self.keys = keys
        self.error = error
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True

    def metadata_list(self):
        if self.error:
            raise self.error
        return [(key, "value") for key in self.keys]


class FakeIoctx:
    def __init__(self, pool):
        self.pool = pool
        self.closed = False

    def close(self):
        self.closed = True


class FakeCluster:
    def __init__(self, conffile=None):
        self.conffile = conffile
        self.connected = False
        self.shutdown_called = False
        self.ioctx = None

    def connect(self):
        self.connected = True

    def open_ioctx(self, pool):
        self.ioctx = FakeIoctx(pool)
        return self.ioctx

    def shutdown(self):
        self.shutdown_called = True


@pytest.fixture
def ceph(monkeypatch):
    """Wire the rados/rbd stubs to fakes and hand back what they recorded."""
    state = {}

    def install(keys=("os", "role"), error=None):
        def rados_ctor(conffile=None):
            state["cluster"] = FakeCluster(conffile)
            return state["cluster"]

        def image_ctor(ioctx, name):
            state["image"] = FakeImage(ioctx, name, keys, error)
            return state["image"]

        monkeypatch.setattr(get_metadata.rados, "Rados", rados_ctor, raising=False)
        monkeypatch.setattr(get_metadata.rbd, "Image", image_ctor, raising=False)
        return state

    return install


def test_prints_every_metadata_key(ceph, capsys):
    ceph(keys=("os", "role", "seapath"))

    get_metadata.print_metadata_keys("guest0")

    assert capsys.readouterr().out == "os\nrole\nseapath\n"


def test_prints_nothing_when_the_image_has_no_metadata(ceph, capsys):
    ceph(keys=())

    get_metadata.print_metadata_keys("guest0")

    assert capsys.readouterr().out == ""


def test_opens_the_system_image_of_the_guest(ceph):
    state = ceph()

    get_metadata.print_metadata_keys("guest0")

    assert state["image"].name == "system_guest0"
    assert state["image"].ioctx is state["cluster"].ioctx


def test_reads_the_rbd_pool_through_the_default_configuration(ceph):
    state = ceph()

    get_metadata.print_metadata_keys("guest0")

    assert state["cluster"].conffile == "/etc/ceph/ceph.conf"
    assert state["cluster"].connected is True
    assert state["cluster"].ioctx.pool == "rbd"


def test_closes_the_image_the_context_and_the_cluster(ceph):
    state = ceph()

    get_metadata.print_metadata_keys("guest0")

    assert state["image"].closed is True
    assert state["cluster"].ioctx.closed is True
    assert state["cluster"].shutdown_called is True


def test_releases_the_cluster_even_when_the_image_fails(ceph):
    state = ceph(error=RuntimeError("image is gone"))

    with pytest.raises(RuntimeError):
        get_metadata.print_metadata_keys("guest0")

    assert state["cluster"].ioctx.closed is True
    assert state["cluster"].shutdown_called is True


def test_main_passes_the_guest_name_through(ceph, capsys):
    state = ceph()

    get_metadata.main(["get_metadata.py", "guest1"])

    assert state["image"].name == "system_guest1"
    assert capsys.readouterr().out == "os\nrole\n"


def test_main_falls_back_to_sys_argv(ceph, monkeypatch):
    state = ceph()
    monkeypatch.setattr(
        get_metadata.sys, "argv", ["get_metadata.py", "guest2"]
    )

    get_metadata.main()

    assert state["image"].name == "system_guest2"


@pytest.mark.parametrize(
    "argv",
    [
        ["get_metadata.py"],
        ["get_metadata.py", "guest0", "extra"],
    ],
)
def test_main_rejects_a_wrong_argument_count(ceph, capsys, argv):
    ceph()

    with pytest.raises(SystemExit) as excinfo:
        get_metadata.main(argv)

    assert excinfo.value.code == 1
    assert "usage: get_metadata.py <guest>" in capsys.readouterr().err
