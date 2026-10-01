# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/backup_restore/files/scripts/get_containers.py."""

import pytest

from support import install_stub_module, load_script

# rados and rbd are the Ceph C bindings; they only exist on a deployed node.
install_stub_module("rados")
install_stub_module("rbd")

get_containers = load_script("roles/backup_restore/files/scripts/get_containers.py")


class ImageNotFound(Exception):
    pass


class FakeImage:
    def __init__(self, state, ioctx, name, read_only=False):
        if name not in state["pool"]:
            raise ImageNotFound(name)
        self.name = name
        self.read_only = read_only
        self.keys = state["pool"][name]
        state["opened"].append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True

    def metadata_list(self):
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
        self.ioctx = None
        self.shutdown_called = False

    def connect(self):
        pass

    def open_ioctx(self, pool):
        self.ioctx = FakeIoctx(pool)
        return self.ioctx

    def shutdown(self):
        self.shutdown_called = True


@pytest.fixture
def ceph(monkeypatch):
    """A pool whose images carry the metadata keys given, and what was opened."""

    def install(pool, listed=None):
        state = {"pool": pool, "opened": []}

        class FakeRBD:
            def list(self, ioctx):
                return list(pool if listed is None else listed)

        def rados_ctor(conffile=None):
            state["cluster"] = FakeCluster(conffile)
            return state["cluster"]

        monkeypatch.setattr(get_containers.rados, "Rados", rados_ctor, raising=False)
        monkeypatch.setattr(get_containers.rbd, "RBD", FakeRBD, raising=False)
        monkeypatch.setattr(
            get_containers.rbd,
            "Image",
            lambda ioctx, name, read_only=False: FakeImage(
                state, ioctx, name, read_only
            ),
            raising=False,
        )
        monkeypatch.setattr(
            get_containers.rbd, "ImageNotFound", ImageNotFound, raising=False
        )
        return state

    return install


def test_lists_the_images_deploy_containers_cluster_recorded(ceph):
    ceph(
        {
            "system_guest0": ["xml", "_priority"],
            "data_guest0_0": [],
            "relay": ["seapath.images"],
            "nginx": ["seapath.images", "other"],
        }
    )

    assert get_containers.list_containers() == ["nginx", "relay"]


def test_leaves_out_the_images_put_aside(ceph):
    state = ceph(
        {
            "nginx": ["seapath.images"],
            "nginx.20260927T101500Z-1.0": ["seapath.images"],
        }
    )

    assert get_containers.list_containers() == ["nginx"]
    assert [image.name for image in state["opened"]] == ["nginx"]


def test_opens_the_images_read_only(ceph):
    state = ceph({"nginx": ["seapath.images"]})

    get_containers.list_containers()

    assert state["opened"][0].read_only is True


def test_skips_an_image_removed_since_the_listing(ceph):
    ceph({"nginx": ["seapath.images"]}, listed=["gone", "nginx"])

    assert get_containers.list_containers() == ["nginx"]


def test_reads_the_rbd_pool_and_releases_the_cluster(ceph):
    state = ceph({})

    get_containers.list_containers()

    assert state["cluster"].conffile == "/etc/ceph/ceph.conf"
    assert state["cluster"].ioctx.pool == "rbd"
    assert state["cluster"].ioctx.closed is True
    assert state["cluster"].shutdown_called is True


def test_main_prints_one_workload_per_line(ceph, capsys):
    ceph({"relay": ["seapath.images"], "nginx": ["seapath.images"]})

    get_containers.main(["get_containers.py"])

    assert capsys.readouterr().out == "nginx\nrelay\n"


def test_main_falls_back_to_sys_argv(ceph, monkeypatch, capsys):
    ceph({"nginx": ["seapath.images"]})
    monkeypatch.setattr(get_containers.sys, "argv", ["get_containers.py"])

    get_containers.main()

    assert capsys.readouterr().out == "nginx\n"


def test_main_takes_no_argument(ceph, capsys):
    ceph({})

    with pytest.raises(SystemExit) as excinfo:
        get_containers.main(["get_containers.py", "extra"])

    assert excinfo.value.code == 1
    assert "usage: get_containers.py" in capsys.readouterr().err
