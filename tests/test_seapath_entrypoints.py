# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the two seapath-alloc entry points installed in /usr/bin.

Unlike every other script in this suite, these call main() at import time:
they are argv-transparent shims whose only job is to put /usr/lib/seapath on
sys.path and hand over to the package. Loading one is therefore running it.
"""

from support import add_seapath_alloc_to_path, load_script

add_seapath_alloc_to_path()


def test_seapath_alloc_hands_over_to_the_cli(monkeypatch):
    from seapath_alloc import cli

    called = []
    monkeypatch.setattr(cli, "main", lambda: called.append("cli"))

    load_script("roles/deploy_seapath_alloc/files/seapath-alloc",
                "seapath_alloc_bin")

    assert called == ["cli"]


def test_seapath_qemu_hook_hands_over_to_the_hook(monkeypatch):
    from seapath_alloc import hook

    called = []
    monkeypatch.setattr(hook, "main", lambda: called.append("hook"))

    load_script("roles/deploy_seapath_alloc/files/seapath-qemu-hook",
                "seapath_qemu_hook_bin")

    assert called == ["hook"]
