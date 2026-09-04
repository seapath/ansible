# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""Tests for the host real-time tuning readings of conformance.py.

Every reading is exercised twice: the value it comes back with on a tuned
machine, and what it reports when the file is not there. The second case is
the one that matters most, because a reading that quietly returns a default
would tell a management interface that a machine is tuned when nobody looked.
"""

import os

import pytest

from seapath_alloc import conformance
from seapath_alloc.conformance import (
    IRQ_DETAIL_LIMIT,
    acpi_present,
    collect,
    hugepages,
    irq_affinity,
    kernel_cmdline,
    sched_rt,
    smt,
    transparent_hugepages,
    tuned_profile,
)


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


@pytest.fixture
def etc(tmp_path):
    return str(tmp_path / "etc")


@pytest.fixture
def usr(tmp_path):
    return str(tmp_path / "usr")


@pytest.fixture
def proc(tmp_path):
    return str(tmp_path / "proc")


@pytest.fixture
def sysfs(tmp_path):
    return str(tmp_path / "sys")


# --- tuned ----------------------------------------------------------------


def test_tuned_reads_the_configured_profile(etc, usr):
    write(os.path.join(etc, "tuned", "active_profile"), "seapath-rt-host\n")
    os.makedirs(os.path.join(etc, "tuned", "profiles", "seapath-rt-host"))

    assert tuned_profile(etc, usr) == {
        "profile": "seapath-rt-host",
        "source": os.path.join(etc, "tuned", "active_profile"),
        "installed": True,
    }


def test_tuned_accepts_a_profile_shipped_by_the_distribution(etc, usr):
    write(os.path.join(etc, "tuned", "active_profile"), "realtime\n")
    os.makedirs(os.path.join(usr, "lib", "tuned", "realtime"))

    assert tuned_profile(etc, usr)["installed"] is True


def test_tuned_reports_a_profile_that_is_installed_nowhere(etc, usr):
    write(os.path.join(etc, "tuned", "active_profile"), "seapath-rt-host\n")

    reading = tuned_profile(etc, usr)

    assert reading["profile"] == "seapath-rt-host"
    assert reading["installed"] is False


def test_tuned_reports_no_profile_rather_than_a_default(etc, usr):
    assert tuned_profile(etc, usr) == {
        "profile": "",
        "source": "",
        "installed": None,
    }


# --- kernel command line --------------------------------------------------


def test_cmdline_is_read_verbatim(proc):
    line = "BOOT_IMAGE=/vmlinuz isolcpus=4-11 nohz_full=4-11 rcu_nocbs=4-11"
    write(os.path.join(proc, "cmdline"), line + "\n")

    assert kernel_cmdline(proc) == line


def test_cmdline_is_empty_when_it_cannot_be_read(proc):
    assert kernel_cmdline(proc) == ""


# --- RT throttling --------------------------------------------------------


def test_sched_rt_reads_both_sysctls(proc):
    write(os.path.join(proc, "sys/kernel/sched_rt_runtime_us"), "950000\n")
    write(os.path.join(proc, "sys/kernel/sched_rt_period_us"), "1000000\n")

    assert sched_rt(proc) == {"runtime_us": 950000, "period_us": 1000000}


def test_sched_rt_keeps_the_disabled_value(proc):
    """-1 is what the realtime profile sets, and never an unreadable file."""
    write(os.path.join(proc, "sys/kernel/sched_rt_runtime_us"), "-1\n")

    assert sched_rt(proc)["runtime_us"] == -1


def test_sched_rt_reports_nothing_when_the_sysctls_are_absent(proc):
    assert sched_rt(proc) == {"runtime_us": None, "period_us": None}


# --- hugepages ------------------------------------------------------------


def make_pool(root, size_kb, total, free=None):
    entry = os.path.join(root, "hugepages-%dkB" % size_kb)
    write(os.path.join(entry, "nr_hugepages"), "%d\n" % total)
    if free is not None:
        write(os.path.join(entry, "free_hugepages"), "%d\n" % free)


def test_hugepages_reads_the_machine_wide_pools(sysfs):
    root = os.path.join(sysfs, "kernel/mm/hugepages")
    make_pool(root, 1048576, 16, free=8)
    make_pool(root, 2048, 512, free=512)

    # Ordered by directory name, which is what the kernel calls them and what
    # makes the exposition stable from one scrape to the next.
    assert hugepages(sysfs) == [
        {"size_kb": 1048576, "node": None, "total": 16, "free": 8},
        {"size_kb": 2048, "node": None, "total": 512, "free": 512},
    ]


def test_hugepages_reads_each_numa_node(sysfs):
    make_pool(os.path.join(sysfs, "kernel/mm/hugepages"), 1048576, 16, free=16)
    node_root = os.path.join(sysfs, "devices/system/node")
    make_pool(os.path.join(node_root, "node0", "hugepages"), 1048576, 16, free=16)
    make_pool(os.path.join(node_root, "node1", "hugepages"), 1048576, 0, free=0)

    starved = [p for p in hugepages(sysfs) if p["node"] == 1]

    assert starved == [{"size_kb": 1048576, "node": 1, "total": 0, "free": 0}]


def test_hugepages_ignores_a_pool_with_no_count(sysfs):
    root = os.path.join(sysfs, "kernel/mm/hugepages")
    os.makedirs(os.path.join(root, "hugepages-2048kB"))

    assert hugepages(sysfs) == []


def test_hugepages_defaults_free_to_zero_rather_than_dropping_the_pool(sysfs):
    make_pool(os.path.join(sysfs, "kernel/mm/hugepages"), 2048, 4)

    assert hugepages(sysfs) == [
        {"size_kb": 2048, "node": None, "total": 4, "free": 0}
    ]


def test_hugepages_of_a_kernel_that_exposes_none(sysfs):
    assert hugepages(sysfs) == []


# --- transparent hugepages ------------------------------------------------


def test_transparent_hugepages_reads_the_selected_choice(sysfs):
    root = os.path.join(sysfs, "kernel/mm/transparent_hugepage")
    write(os.path.join(root, "enabled"), "always madvise [never]\n")
    write(os.path.join(root, "defrag"), "always defer [madvise] never\n")

    assert transparent_hugepages(sysfs) == {
        "enabled": "never",
        "defrag": "madvise",
    }


def test_transparent_hugepages_is_empty_when_the_kernel_has_no_control(sysfs):
    assert transparent_hugepages(sysfs) == {"enabled": "", "defrag": ""}


# --- SMT ------------------------------------------------------------------


def test_smt_reads_active_and_control(sysfs):
    root = os.path.join(sysfs, "devices/system/cpu/smt")
    write(os.path.join(root, "active"), "1\n")
    write(os.path.join(root, "control"), "on\n")

    assert smt(sysfs) == {"active": True, "control": "on"}


def test_smt_reports_off_apart_from_absent(sysfs):
    root = os.path.join(sysfs, "devices/system/cpu/smt")
    write(os.path.join(root, "active"), "0\n")
    write(os.path.join(root, "control"), "forceoff\n")

    assert smt(sysfs) == {"active": False, "control": "forceoff"}


def test_smt_of_a_machine_that_exposes_no_control(sysfs):
    assert smt(sysfs) == {"active": None, "control": ""}


# --- ACPI -----------------------------------------------------------------


def test_acpi_present(sysfs):
    os.makedirs(os.path.join(sysfs, "firmware/acpi"))

    assert acpi_present(sysfs) is True


def test_acpi_absent(sysfs):
    assert acpi_present(sysfs) is False


# --- interrupt affinity ---------------------------------------------------


def make_irq(proc, number, cpus, device=None):
    entry = os.path.join(proc, "irq", str(number))
    write(os.path.join(entry, "smp_affinity_list"), cpus + "\n")
    if device:
        os.makedirs(os.path.join(entry, device))


def test_irq_reports_nothing_readable_apart_from_an_idle_machine(proc):
    """total None is "/proc/irq told me nothing", not "no interrupt"."""
    assert irq_affinity([4, 5], proc) == {
        "total": None, "on_isolated": 0, "detail": []
    }


def test_irq_counts_without_judging_when_nothing_is_isolated(proc):
    make_irq(proc, 10, "0-11")
    make_irq(proc, 11, "0-11")

    assert irq_affinity([], proc) == {
        "total": 2, "on_isolated": 0, "detail": []
    }


def test_irq_names_the_device_reaching_an_isolated_cpu(proc):
    make_irq(proc, 10, "0-3")
    make_irq(proc, 181, "0-11", device="eno1-TxRx-0")

    reading = irq_affinity([4, 5], proc)

    assert reading["total"] == 2
    assert reading["on_isolated"] == 1
    assert reading["detail"] == [
        {"irq": "181", "name": "eno1-TxRx-0", "cpus": [4, 5]}
    ]


def test_irq_reports_the_overlap_rather_than_the_whole_mask(proc):
    make_irq(proc, 181, "3-6")

    assert irq_affinity([4, 5, 8], proc)["detail"][0]["cpus"] == [4, 5]


def test_irq_leaves_the_name_empty_when_no_handler_is_named(proc):
    make_irq(proc, 181, "4")

    assert irq_affinity([4], proc)["detail"][0]["name"] == ""


def test_irq_skips_an_unreadable_affinity(proc):
    os.makedirs(os.path.join(proc, "irq", "10"))
    make_irq(proc, 11, "4")

    reading = irq_affinity([4], proc)

    assert reading["total"] == 2
    assert reading["on_isolated"] == 1


def test_irq_caps_the_detail_and_keeps_the_count_true(proc):
    """A machine keeping nothing off its isolated cores is the worst case.

    Every interrupt is then a finding, and one series per interrupt per node
    is a cardinality bill the count already covers.
    """
    for number in range(100, 100 + IRQ_DETAIL_LIMIT + 5):
        make_irq(proc, number, "0-11")

    reading = irq_affinity([4, 5], proc)

    assert reading["on_isolated"] == IRQ_DETAIL_LIMIT + 5
    assert len(reading["detail"]) == IRQ_DETAIL_LIMIT


def test_irq_ignores_the_non_numeric_entries_of_proc_irq(proc):
    make_irq(proc, 10, "4")
    write(os.path.join(proc, "irq", "default_smp_affinity"), "fff\n")

    assert irq_affinity([4], proc)["total"] == 1


# --- collect --------------------------------------------------------------


def test_collect_returns_every_reading(tmp_path, proc, sysfs, etc, usr):
    write(os.path.join(etc, "tuned", "active_profile"), "seapath-rt-host\n")
    os.makedirs(os.path.join(etc, "tuned", "profiles", "seapath-rt-host"))
    write(os.path.join(proc, "cmdline"), "isolcpus=4-11 nohz_full=4-11\n")
    write(os.path.join(proc, "sys/kernel/sched_rt_runtime_us"), "-1\n")
    write(os.path.join(proc, "sys/kernel/sched_rt_period_us"), "1000000\n")
    make_pool(os.path.join(sysfs, "kernel/mm/hugepages"), 1048576, 16, free=16)
    write(os.path.join(sysfs, "kernel/mm/transparent_hugepage/enabled"),
          "always madvise [never]\n")
    write(os.path.join(sysfs, "devices/system/cpu/smt/active"), "1\n")
    os.makedirs(os.path.join(sysfs, "firmware/acpi"))
    make_irq(proc, 181, "0-11", device="eno1-TxRx-0")

    reading = collect(isolated=[4, 5], proc_path=proc, sys_path=sysfs,
                      etc_path=etc, usr_path=usr)

    assert reading["tuned"]["profile"] == "seapath-rt-host"
    assert reading["cmdline"] == "isolcpus=4-11 nohz_full=4-11"
    assert reading["sched_rt"]["runtime_us"] == -1
    assert reading["hugepages"][0]["total"] == 16
    assert reading["thp"]["enabled"] == "never"
    assert reading["smt"]["active"] is True
    assert reading["acpi"] is True
    assert reading["irq"]["on_isolated"] == 1


def test_collect_on_a_machine_where_nothing_can_be_read(tmp_path):
    empty = str(tmp_path / "nowhere")

    reading = collect(isolated=[], proc_path=empty, sys_path=empty,
                      etc_path=empty, usr_path=empty)

    assert reading["tuned"]["profile"] == ""
    assert reading["cmdline"] == ""
    assert reading["sched_rt"] == {"runtime_us": None, "period_us": None}
    assert reading["hugepages"] == []
    assert reading["smt"]["active"] is None
    assert reading["acpi"] is False
    assert reading["irq"]["total"] is None


def test_collect_reads_the_real_host_by_default(monkeypatch):
    """The defaults are the host's own paths, which is what the timer runs."""
    seen = {}

    def spy(name):
        def record(*args, **kwargs):
            seen[name] = (args, kwargs)
            return {} if name != "acpi" else False
        return record

    monkeypatch.setattr(conformance, "tuned_profile", spy("tuned"))
    monkeypatch.setattr(conformance, "kernel_cmdline", spy("cmdline"))
    monkeypatch.setattr(conformance, "sched_rt", spy("sched_rt"))
    monkeypatch.setattr(conformance, "hugepages", spy("hugepages"))
    monkeypatch.setattr(conformance, "transparent_hugepages", spy("thp"))
    monkeypatch.setattr(conformance, "smt", spy("smt"))
    monkeypatch.setattr(conformance, "acpi_present", spy("acpi"))
    monkeypatch.setattr(conformance, "irq_affinity", spy("irq"))

    collect()

    assert seen["tuned"][0] == ("/etc", "/usr")
    assert seen["cmdline"][0] == ("/proc",)
    assert seen["hugepages"][0] == ("/sys",)
    assert seen["irq"][0] == ((), "/proc")
