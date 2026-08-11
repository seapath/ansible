# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for scripts/get_osd.py."""

import json

import pytest

from support import load_script

get_osd = load_script("scripts/get_osd.py")


class FakeCompletedProcess:
    def __init__(self, stdout=b""):
        self.stdout = stdout


@pytest.fixture
def fake_run(monkeypatch):
    """Record subprocess.run calls and feed a crushmap back to the script."""
    calls = []

    def runner(crushmap):
        def _run(args, **kwargs):
            calls.append((args, kwargs))
            if args[0] == "crushtool":
                return FakeCompletedProcess(json.dumps(crushmap).encode("UTF-8"))
            return FakeCompletedProcess()

        monkeypatch.setattr(get_osd.subprocess, "run", _run)
        return calls

    return runner


def crushmap(*buckets):
    return {"buckets": list(buckets)}


def host(name, *osd_ids):
    return {
        "type_name": "host",
        "name": name,
        "items": [{"id": i} for i in osd_ids],
    }


def test_prints_the_osd_ids_of_the_host(fake_run, capsys):
    fake_run(crushmap(host("hypervisor1", 0, 3, 7)))

    get_osd.print_osd_on_host("hypervisor1")

    assert capsys.readouterr().out == "0,3,7\n"


def test_dumps_the_crushmap_before_decoding_it(fake_run):
    calls = fake_run(crushmap(host("hypervisor1", 1)))

    get_osd.print_osd_on_host("hypervisor1")

    dump, decode = calls
    assert dump[0] == "ceph osd getcrushmap > ./crushmap"
    assert dump[1]["shell"] is True
    assert dump[1]["check"] is True
    assert decode[0] == [
        "crushtool", "-d", "./crushmap", "-f", "json", "--dump", "-o", "/dev/null",
    ]
    assert decode[1]["shell"] is False


def test_prints_nothing_when_the_host_is_absent(fake_run, capsys):
    fake_run(crushmap(host("hypervisor2", 0)))

    get_osd.print_osd_on_host("hypervisor1")

    assert capsys.readouterr().out == ""


def test_prints_nothing_when_the_host_has_no_osd(fake_run, capsys):
    fake_run(crushmap(host("hypervisor1")))

    get_osd.print_osd_on_host("hypervisor1")

    assert capsys.readouterr().out == ""


def test_ignores_a_non_host_bucket_of_the_same_name(fake_run, capsys):
    root = {"type_name": "root", "name": "hypervisor1", "items": [{"id": 9}]}
    fake_run(crushmap(root, host("hypervisor1", 4)))

    get_osd.print_osd_on_host("hypervisor1")

    assert capsys.readouterr().out == "4\n"


def test_stops_at_the_first_matching_host(fake_run, capsys):
    fake_run(crushmap(host("hypervisor1", 1), host("hypervisor1", 2)))

    get_osd.print_osd_on_host("hypervisor1")

    assert capsys.readouterr().out == "1\n"


def test_main_passes_the_hostname_argument_through(fake_run, capsys):
    fake_run(crushmap(host("hypervisor3", 5)))

    get_osd.main(["hypervisor3"])

    assert capsys.readouterr().out == "5\n"


def test_main_rejects_a_missing_hostname(fake_run):
    fake_run(crushmap())

    with pytest.raises(SystemExit) as excinfo:
        get_osd.main([])

    assert excinfo.value.code == 2
