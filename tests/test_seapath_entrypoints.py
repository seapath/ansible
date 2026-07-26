# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the seapath-qemu-hook entry point installed in /usr/bin.

Unlike every other script in this suite, it calls main() at import time: it is
an argv-transparent shim whose only job is to put /usr/lib/seapath on sys.path
and hand over to the package. Loading it is therefore running it.
"""

from support import add_seapath_alloc_to_path, load_script

add_seapath_alloc_to_path()


def test_seapath_qemu_hook_hands_over_to_the_hook(monkeypatch):
    from seapath_alloc import hook

    called = []
    monkeypatch.setattr(hook, "main", lambda: called.append("hook"))

    load_script("roles/deploy_seapath_alloc/files/seapath-qemu-hook",
                "seapath_qemu_hook_bin")

    assert called == ["hook"]
