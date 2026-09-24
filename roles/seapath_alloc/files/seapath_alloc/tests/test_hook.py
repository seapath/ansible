# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import io
import types

import pytest

from seapath_alloc import hook as hook_mod
from seapath_alloc.hook import handle_start, main
from seapath_alloc.threads import QemuThreads


class FakePool:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def libvirt(monkeypatch):
    """
    Replace everything handle_start() reaches for and report what it did.

    The hook is the one component that must never raise: libvirt aborts the
    VM start on a non-zero exit.
    """
    state = {"applied": []}

    def install(threads=None, vcpu_count=2, profile=None):
        if threads is None:
            threads = QemuThreads(pid=1000, emulator_tid=1000,
                                  vcpu_tids=[1010, 1011],
                                  vhost_tids=[1020], iothread_tids=[1030])
        state["threads"] = threads

        monkeypatch.setattr(hook_mod, "Topology", lambda **kw: "topo")
        monkeypatch.setattr(hook_mod, "CorePool", lambda **kw: FakePool())
        monkeypatch.setattr(
            hook_mod, "load_profile",
            lambda name, domain_xml="": (
                state.update(profile_args=(name, domain_xml)),
                profile or {"groups": []})[1],
        )
        monkeypatch.setattr(
            hook_mod, "get_vcpu_count",
            lambda name, domain_xml="": vcpu_count,
        )
        monkeypatch.setattr(
            hook_mod, "discover",
            lambda name, expected_vcpus=1: (
                state.update(discover_args=(name, expected_vcpus)), threads)[1],
        )
        monkeypatch.setattr(
            hook_mod, "expand_group_specs",
            lambda profile_arg, **kw: (state.update(expand_kwargs=kw), ["spec"])[1],
        )
        monkeypatch.setattr(
            hook_mod, "allocate_cores",
            lambda pool, specs, topo, **kw: (
                state.update(allocate_kwargs=kw),
                types.SimpleNamespace(allocations=["alloc"]))[1],
        )
        monkeypatch.setattr(
            hook_mod, "apply_all",
            lambda t, allocations: state["applied"].append((t, allocations)),
        )
        return state

    return install


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch):
    monkeypatch.setattr(hook_mod, "setup_logging", lambda *a, **kw: None)


def run_main(monkeypatch, argv, stdin="<domain/>"):
    monkeypatch.setattr(hook_mod.sys, "argv", argv)
    monkeypatch.setattr(hook_mod.sys, "stdin", io.StringIO(stdin))
    with pytest.raises(SystemExit) as excinfo:
        main()
    return excinfo.value.code


# --- handle_start ---------------------------------------------------------


def test_handle_start_applies_the_allocation(libvirt):
    state = libvirt()

    handle_start("vm0", domain_xml="<domain/>")

    threads, allocations = state["applied"][0]
    assert threads is state["threads"]
    assert allocations == ["alloc"]


def test_handle_start_passes_the_domain_xml_around(libvirt):
    state = libvirt()

    handle_start("vm0", domain_xml="<domain>xml</domain>")

    assert state["profile_args"] == ("vm0", "<domain>xml</domain>")


def test_handle_start_sizes_the_groups_from_the_discovered_threads(libvirt):
    state = libvirt(vcpu_count=2)

    handle_start("vm0")

    assert state["expand_kwargs"] == {
        "vcpu_count": 2, "vhost_count": 1, "iothread_count": 1,
    }


def test_handle_start_waits_for_the_expected_vcpu_count(libvirt):
    state = libvirt(vcpu_count=4)

    handle_start("vm0")

    assert state["discover_args"] == ("vm0", 4)


def test_handle_start_excludes_the_vm_own_threads_from_the_pool(libvirt):
    """
    The VM's own QEMU process must not count as busy against itself, or it
    would see the cores it is about to take as already used.
    """
    state = libvirt()

    handle_start("vm0")

    assert state["allocate_kwargs"]["exclude_pids"] == {1000}
    assert state["allocate_kwargs"]["pid"] == 1000
    assert state["allocate_kwargs"]["label"] == "VM vm0"


def test_handle_start_logs_and_returns_when_qemu_is_not_found(
    monkeypatch, libvirt, caplog
):
    state = libvirt()
    monkeypatch.setattr(hook_mod, "discover", lambda name, expected_vcpus=1: None)

    with caplog.at_level("ERROR", logger=hook_mod.log.name):
        handle_start("vm0")

    assert state["applied"] == []
    assert "VM vm0: QEMU process not found, pinning skipped" in caplog.text


# --- main -----------------------------------------------------------------


def test_main_ignores_a_call_with_too_few_arguments(monkeypatch, libvirt):
    state = libvirt()

    assert run_main(monkeypatch, ["hook", "vm0", "started"]) == 0
    assert state["applied"] == []


@pytest.mark.parametrize("sub_op", ["begin", "incoming"])
def test_main_pins_on_a_vm_start(monkeypatch, libvirt, sub_op):
    state = libvirt()

    assert run_main(monkeypatch, ["hook", "vm0", "started", sub_op]) == 0
    assert len(state["applied"]) == 1


@pytest.mark.parametrize(
    "operation,sub_op",
    [
        ("stopped", "end"),
        ("started", "end"),
        ("prepare", "begin"),
        ("migrate", "begin"),
    ],
)
def test_main_ignores_every_other_event(monkeypatch, libvirt, operation, sub_op):
    state = libvirt()

    assert run_main(monkeypatch, ["hook", "vm0", operation, sub_op]) == 0
    assert state["applied"] == []


def test_main_reads_the_domain_xml_from_stdin(monkeypatch, libvirt):
    state = libvirt()

    run_main(monkeypatch, ["hook", "vm0", "started", "begin"],
             stdin="<domain>from stdin</domain>")

    assert state["profile_args"] == ("vm0", "<domain>from stdin</domain>")


def test_main_never_fails_the_vm_start(monkeypatch, libvirt, caplog):
    """A non-zero exit makes libvirt abort the VM: pinning failures must not."""
    libvirt()
    monkeypatch.setattr(
        hook_mod, "discover",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no /proc")),
    )

    with caplog.at_level("ERROR", logger=hook_mod.log.name):
        code = run_main(monkeypatch, ["hook", "vm0", "started", "begin"])

    assert code == 0
    assert "VM vm0: pinning failed" in caplog.text
    assert "RuntimeError" in caplog.text
