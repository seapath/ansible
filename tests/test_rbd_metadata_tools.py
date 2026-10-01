# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for the two scripts writing RBD metadata through the Ceph bindings.

roles/deploy_containers_cluster/files/seapath-rbd-meta records the definition
of a workload on its image, and roles/backup_restore/files/scripts/
restore_metadata.py writes back what a backup exported. Both read the value
from somewhere other than the command line, which would hold 128 KiB at most.
"""

import io
import json

import pytest

from support import install_stub_module, load_script

install_stub_module("rados")
install_stub_module("rbd")

rbd_meta = load_script(
    "roles/deploy_containers_cluster/files/seapath-rbd-meta", "seapath_rbd_meta"
)
restore_metadata = load_script(
    "roles/backup_restore/files/scripts/restore_metadata.py"
)

LARGE = "x" * (300 * 1024)


class FakeImage:
    def __init__(self, state, ioctx, name):
        self.state = state
        self.name = name
        state["opened"].append((ioctx.pool, name))

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def metadata_list(self):
        return list(self.state["metadata"].items())

    def metadata_set(self, key, value):
        self.state["metadata"][key] = value
        self.state["written"].append(key)


class FakeIoctx:
    def __init__(self, pool):
        self.pool = pool

    def close(self):
        self.closed = True


class FakeCluster:
    def __init__(self, conffile=None):
        self.conffile = conffile

    def connect(self):
        pass

    def open_ioctx(self, pool):
        return FakeIoctx(pool)

    def shutdown(self):
        self.shutdown_called = True


@pytest.fixture
def ceph(monkeypatch):
    # Both scripts import the same stub modules, so patching them once is
    # patching them for both.
    module = rbd_meta
    state = {"metadata": {}, "opened": [], "written": []}
    monkeypatch.setattr(module.rados, "Rados", FakeCluster, raising=False)
    monkeypatch.setattr(
        module.rbd,
        "Image",
        lambda ioctx, name: FakeImage(state, ioctx, name),
        raising=False,
    )
    return state


def test_records_a_value_larger_than_an_argument(ceph):
    changed = rbd_meta.set_metadata("rbd/relay", "seapath.definition", LARGE)

    assert changed is True
    assert ceph["metadata"]["seapath.definition"] == LARGE
    assert ceph["opened"] == [("rbd", "relay")]


def test_leaves_a_value_the_image_holds(ceph):
    ceph["metadata"]["seapath.definition"] = "same"

    assert rbd_meta.set_metadata("rbd/relay", "seapath.definition", "same") is False
    assert ceph["written"] == []


def test_meta_reads_the_value_from_standard_input(ceph, capsys):
    rbd_meta.main(
        ["seapath-rbd-meta", "rbd/relay", "seapath.definition"], io.StringIO(LARGE)
    )

    assert ceph["metadata"]["seapath.definition"] == LARGE
    assert capsys.readouterr().out == "changed\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["seapath-rbd-meta", "rbd/relay"],
        ["seapath-rbd-meta", "relay", "seapath.definition"],
    ],
)
def test_meta_refuses_a_wrong_command_line(ceph, argv, capsys):
    with pytest.raises(SystemExit) as excinfo:
        rbd_meta.main(argv, io.StringIO("value"))

    assert excinfo.value.code == 1
    assert ceph["written"] == []


def test_restores_every_key_of_the_backup(ceph, tmp_path, capsys):
    exported = tmp_path / "202610011813.json"
    exported.write_text(
        json.dumps({"seapath.images": "localhost/relay:1", "seapath.definition": LARGE})
        + "\n"
    )

    restore_metadata.main(["restore_metadata.py", "rbd/relay", str(exported)])

    assert ceph["metadata"] == {
        "seapath.images": "localhost/relay:1",
        "seapath.definition": LARGE,
    }
    assert capsys.readouterr().out == (
        "metadata name = seapath.definition\nmetadata name = seapath.images\n"
    )


def test_an_image_exported_without_metadata_gets_none(ceph, tmp_path):
    # rbd writes nothing at all for an image without metadata.
    exported = tmp_path / "202610011813.json"
    exported.write_text("")

    restore_metadata.main(["restore_metadata.py", "rbd/relay", str(exported)])

    assert ceph["written"] == []


def test_restore_refuses_a_wrong_command_line(ceph, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        restore_metadata.main(["restore_metadata.py", "relay", str(tmp_path / "x")])

    assert excinfo.value.code == 1


def test_restore_takes_two_arguments(ceph, capsys):
    with pytest.raises(SystemExit) as excinfo:
        restore_metadata.main(["restore_metadata.py", "rbd/relay"])

    assert excinfo.value.code == 1
    assert "usage: restore_metadata.py" in capsys.readouterr().err
