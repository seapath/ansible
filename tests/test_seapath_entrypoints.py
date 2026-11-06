# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the two seapath-alloc entry points installed in /usr/bin.

Unlike every other script in this suite, these call main() at import time:
they are argv-transparent shims whose only job is to put /usr/lib/seapath on
sys.path and hand over to the package. Loading one is therefore running it.
The hook always ends with exit status 0, which libvirt needs to start the VM.
"""

import sys

import pytest

from support import add_seapath_alloc_to_path, load_script

add_seapath_alloc_to_path()

HOOK = "roles/seapath_alloc/files/seapath-qemu-hook"


def run_hook():
    with pytest.raises(SystemExit) as excinfo:
        load_script(HOOK, "seapath_qemu_hook_bin")
    return excinfo.value.code


def test_seapath_alloc_hands_over_to_the_cli(monkeypatch):
    from seapath_alloc import cli

    called = []
    monkeypatch.setattr(cli, "main", lambda: called.append("cli"))

    load_script("roles/seapath_alloc/files/seapath-alloc",
                "seapath_alloc_bin")

    assert called == ["cli"]


def test_seapath_qemu_hook_hands_over_to_the_hook(monkeypatch):
    from seapath_alloc import hook

    called = []
    monkeypatch.setattr(hook, "main", lambda: called.append("hook"))

    assert run_hook() == 0
    assert called == ["hook"]


def test_a_failing_hook_still_exits_0(monkeypatch, capsys):
    from seapath_alloc import hook

    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(hook, "main", broken)

    assert run_hook() == 0
    assert "pinning skipped: RuntimeError('boom')" in capsys.readouterr().err


def test_a_package_that_cannot_be_imported_still_exits_0(monkeypatch, capsys):
    # A partial deployment or a syntax error in the package.
    monkeypatch.setitem(sys.modules, "seapath_alloc.hook", None)

    assert run_hook() == 0
    assert "pinning skipped" in capsys.readouterr().err
