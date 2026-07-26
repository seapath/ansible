# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for roles/seapath_alloc/files/seapath-container-unpin."""

import pytest

from support import add_seapath_alloc_to_path, load_script

add_seapath_alloc_to_path()

unpin = load_script(
    "roles/seapath_alloc/files/seapath-container-unpin",
    "seapath_container_unpin",
)


@pytest.fixture
def harness(monkeypatch):
    record = {"released": []}

    monkeypatch.setattr(unpin, "setup_logging", lambda: None)
    monkeypatch.setattr(unpin, "release", record["released"].append)

    def run(argv):
        monkeypatch.setattr(unpin.sys, "argv",
                            ["seapath-container-unpin"] + argv)
        try:
            unpin.main()
        except SystemExit as exc:
            record["exit"] = exc.code
        else:
            record["exit"] = 0
        return record

    return run


def test_main_rejects_a_wrong_argument_count(harness, capsys):
    record = harness([])

    assert record["exit"] == 1
    assert "usage:" in capsys.readouterr().err
    assert record["released"] == []


@pytest.mark.parametrize("name", ["sv", "sv.service"])
def test_main_releases_the_claim_under_the_bare_name(harness, name, capsys):
    record = harness([name])

    assert record["exit"] == 0
    # The claim is labelled without the .service suffix, as in
    # seapath-container-pin.
    assert record["released"] == ["sv"]
    assert "released claim for sv.service" in capsys.readouterr().out
