# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for plugins/modules/cluster_vm.py."""

import datetime
import sys

import pytest

from support import install_stub_module, load_script

# vm_manager lives in a git submodule the unit job does not check out, and
# ansible-core is not a test dependency. Both are stubbed: what matters here
# is the calls the module makes, not what they do on a real cluster.
install_stub_module("vm_manager")
ansible_basic = install_stub_module("ansible.module_utils.basic")
ansible_text = install_stub_module("ansible.module_utils._text")
ansible_basic.AnsibleModule = object
ansible_text.to_native = str

cluster_vm = load_script("plugins/modules/cluster_vm.py")

# Every vm_manager entry point the module dispatches to.
VM_MANAGER_FUNCTIONS = [
    "list_vms", "create", "clone", "remove", "start", "stop", "disable_vm",
    "status", "enable_vm", "create_snapshot", "purge_image", "remove_snapshot",
    "list_snapshots", "rollback_snapshot", "list_metadata", "get_metadata",
    "add_colocation", "add_pacemaker_remote", "remove_pacemaker_remote",
]


class AnsibleExit(BaseException):
    """
    Base of the fake module's exits.

    AnsibleModule.fail_json and exit_json end the process with SystemExit,
    which derives from BaseException and therefore slips past the
    "except Exception" wrapped around the command dispatch. Deriving from
    BaseException here keeps that behaviour: a fail_json raised inside the
    try block must not be recaught and reported as an unexpected error.
    """

    def __init__(self, kwargs):
        self.kwargs = kwargs
        super().__init__(kwargs.get("msg", ""))


class FailJson(AnsibleExit):
    pass


class ExitJson(AnsibleExit):
    pass


class FakeAnsibleModule:
    def __init__(self, params, init_kwargs):
        self.params = params
        self.init_kwargs = init_kwargs

    def fail_json(self, **kwargs):
        raise FailJson(kwargs)

    def exit_json(self, **kwargs):
        raise ExitJson(kwargs)


@pytest.fixture
def vm_manager(monkeypatch):
    """Record every vm_manager call the module makes."""
    calls = []

    def recorder(name):
        def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            return "{}-result".format(name)

        return call

    for name in VM_MANAGER_FUNCTIONS:
        monkeypatch.setattr(
            cluster_vm.vm_manager, name, recorder(name), raising=False
        )
    return calls


@pytest.fixture
def run(monkeypatch, vm_manager):
    """Run the module with the given parameters and return how it exited."""

    def _run(**params):
        created = {}

        def factory(**init_kwargs):
            created["module"] = FakeAnsibleModule(params, init_kwargs)
            return created["module"]

        monkeypatch.setattr(cluster_vm, "AnsibleModule", factory)
        # A FailJson propagates so tests can assert on it with pytest.raises;
        # a successful run is handed back for inspection.
        try:
            cluster_vm.run_module()
        except ExitJson as exc:
            exc.module = created.get("module")
            return exc
        raise AssertionError("run_module() returned without calling exit_json")

    return _run


def only_call(calls):
    assert len(calls) == 1, calls
    return calls[0]


# --- module wiring --------------------------------------------------------


def test_declares_every_command_it_dispatches():
    assert set(cluster_vm.commands_list) == {
        "create", "remove", "start", "stop", "list_vms", "enable", "disable",
        "status", "clone", "create_snapshot", "remove_snapshot",
        "list_snapshots", "rollback_snapshot", "purge_image", "list_metadata",
        "get_metadata", "define_colocation", "add_pacemaker_remote",
        "remove_pacemaker_remote",
    }


def test_reports_a_missing_vm_manager(run, monkeypatch):
    monkeypatch.setattr(cluster_vm, "HAS_VM_MANAGER", False)

    with pytest.raises(FailJson) as excinfo:
        run(command="list_vms")

    assert "vm_manager" in excinfo.value.kwargs["msg"]


def test_detects_vm_manager_at_import_time():
    # Reloading without the stub takes the ImportError branch of the guard.
    saved = sys.modules.pop("vm_manager")
    try:
        without = load_script("plugins/modules/cluster_vm.py", "cluster_vm_novmm")
    finally:
        sys.modules["vm_manager"] = saved

    assert without.HAS_VM_MANAGER is False
    assert cluster_vm.HAS_VM_MANAGER is True


def test_declares_the_argument_spec_and_the_required_combinations(run):
    result = run(command="list_vms")

    init = result.module.init_kwargs
    assert init["supports_check_mode"] is True
    assert init["mutually_exclusive"] == [("purge_date", "purge_number")]
    assert ("command", "create", ("name", "xml", "system_image")) in init["required_if"]
    assert init["argument_spec"]["command"]["choices"] == cluster_vm.commands_list


def test_main_runs_the_module(monkeypatch):
    called = []
    monkeypatch.setattr(cluster_vm, "run_module", lambda: called.append(True))

    cluster_vm.main()

    assert called == [True]


# --- parameter checking ---------------------------------------------------


def test_requires_a_name_for_every_command_but_list_vms(run):
    with pytest.raises(FailJson) as excinfo:
        run(command="start", name="")

    assert excinfo.value.kwargs["msg"] == (
        "`name` is required when `command` is `start`"
    )


def test_does_not_require_a_name_for_list_vms(run, vm_manager):
    run(command="list_vms")

    assert only_call(vm_manager)[0] == "list_vms"


@pytest.mark.parametrize(
    "params,missing",
    [
        ({"command": "create", "name": "vm0", "xml": "", "system_image": "i"},
         "vm_config"),
        ({"command": "create", "name": "vm0", "xml": "x", "system_image": ""},
         "system_image"),
        ({"command": "clone", "name": "vm0", "src_name": ""}, "src_name"),
        ({"command": "get_metadata", "name": "vm0", "metadata_name": ""},
         "metadata_name"),
        ({"command": "create_snapshot", "name": "vm0", "snapshot_name": ""},
         "snapshot_name"),
        ({"command": "remove_snapshot", "name": "vm0", "snapshot_name": ""},
         "snapshot_name"),
        ({"command": "rollback_snapshot", "name": "vm0", "snapshot_name": ""},
         "snapshot_name"),
    ],
)
def test_reports_the_missing_parameter_of_a_command(run, params, missing):
    with pytest.raises(FailJson) as excinfo:
        run(**params)

    assert missing in excinfo.value.kwargs["msg"]
    assert params["command"] in excinfo.value.kwargs["msg"]


# --- create and clone -----------------------------------------------------


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "system.qcow2"
    path.write_bytes(b"")
    return str(path)


def test_create_passes_the_options_to_vm_manager(run, vm_manager, image):
    run(
        command="create", name="vm0", xml="<domain/>", system_image=image,
        preferred_host="hyp1", priority="100", disk_bus="scsi",
    )

    name, args, _ = only_call(vm_manager)
    assert name == "create"
    options = args[0]
    assert options["name"] == "vm0"
    assert options["base_xml"] == "<domain/>"
    assert options["image"] == image
    assert options["preferred_host"] == "hyp1"
    assert options["priority"] == "100"
    assert options["disk_bus"] == "scsi"


def test_create_defaults_the_disk_bus_to_virtio(run, vm_manager, image):
    run(command="create", name="vm0", xml="<domain/>", system_image=image)

    assert only_call(vm_manager)[1][0]["disk_bus"] == "virtio"


def test_create_rejects_a_system_image_that_is_not_a_file(run, tmp_path):
    with pytest.raises(FailJson) as excinfo:
        run(
            command="create", name="vm0", xml="<domain/>",
            system_image=str(tmp_path / "absent.qcow2"),
        )

    assert "system_image" in excinfo.value.kwargs["msg"]


def test_create_accepts_additional_disks_that_exist(run, vm_manager, image, tmp_path):
    extra = tmp_path / "data.qcow2"
    extra.write_bytes(b"")

    run(
        command="create", name="vm0", xml="<domain/>", system_image=image,
        additional_disks=[str(extra)],
    )

    assert only_call(vm_manager)[1][0]["additional_disks"] == [str(extra)]


def test_create_reports_which_additional_disk_is_missing(run, image, tmp_path):
    extra = tmp_path / "data.qcow2"
    extra.write_bytes(b"")

    with pytest.raises(FailJson) as excinfo:
        run(
            command="create", name="vm0", xml="<domain/>", system_image=image,
            additional_disks=[str(extra), str(tmp_path / "absent.qcow2")],
        )

    assert "additional_disks[1]" in excinfo.value.kwargs["msg"]


def test_clone_names_the_source_and_the_destination(run, vm_manager):
    run(command="clone", name="vm1", src_name="vm0", clear_constraint=True)

    name, args, _ = only_call(vm_manager)
    assert name == "clone"
    assert args[0]["name"] == "vm0"
    assert args[0]["dst_name"] == "vm1"
    assert args[0]["clear_constraint"] is True


def test_clone_forwards_the_pacemaker_overrides(run, vm_manager):
    run(
        command="clone", name="vm1", src_name="vm0",
        pacemaker_meta={"a": "1"}, clear_pacemaker_utilization=True,
    )

    options = only_call(vm_manager)[1][0]
    assert options["pacemaker_meta"] == {"a": "1"}
    assert options["clear_pacemaker_utilization"] is True


# --- lifecycle ------------------------------------------------------------


@pytest.mark.parametrize(
    "command,function",
    [
        ("remove", "remove"),
        ("start", "start"),
        ("stop", "stop"),
        ("disable", "disable_vm"),
    ],
)
def test_lifecycle_commands_take_the_vm_name(run, vm_manager, command, function):
    run(command=command, name="vm0")

    assert only_call(vm_manager) == (function, ("vm0",), {})


def test_enable_forwards_the_nostart_flag(run, vm_manager):
    run(command="enable", name="vm0", nostart=True)

    assert only_call(vm_manager) == ("enable_vm", ("vm0", True), {})


def test_enable_defaults_nostart_to_false(run, vm_manager):
    run(command="enable", name="vm0")

    assert only_call(vm_manager) == ("enable_vm", ("vm0", False), {})


# --- commands returning a value -------------------------------------------


@pytest.mark.parametrize(
    "command,key,function",
    [
        ("list_vms", "list_vms", "list_vms"),
        ("status", "status", "status"),
        ("list_snapshots", "list_snapshot", "list_snapshots"),
        ("list_metadata", "list_metadata", "list_metadata"),
    ],
)
def test_reporting_commands_return_their_result(run, command, key, function):
    result = run(command=command, name="vm0")

    assert isinstance(result, ExitJson)
    assert result.kwargs[key] == "{}-result".format(function)


def test_get_metadata_returns_the_value_of_one_key(run, vm_manager):
    result = run(command="get_metadata", name="vm0", metadata_name="os")

    assert only_call(vm_manager) == ("get_metadata", ("vm0", "os"), {})
    assert result.kwargs["metadata_value"] == "get_metadata-result"


def test_a_command_with_no_output_returns_an_empty_result(run):
    result = run(command="start", name="vm0")

    assert result.kwargs == {}


# --- snapshots ------------------------------------------------------------


@pytest.mark.parametrize(
    "command,function",
    [
        ("create_snapshot", "create_snapshot"),
        ("remove_snapshot", "remove_snapshot"),
        ("rollback_snapshot", "rollback_snapshot"),
    ],
)
def test_snapshot_commands_take_the_snapshot_name(run, vm_manager, command, function):
    run(command=command, name="vm0", snapshot_name="snap1")

    assert only_call(vm_manager) == (function, ("vm0", "snap1"), {})


# --- purge ----------------------------------------------------------------


def test_purge_image_without_a_date_purges_by_count(run, vm_manager):
    run(command="purge_image", name="vm0", purge_number=3)

    assert only_call(vm_manager) == (
        "purge_image", ("vm0",), {"date": None, "number": 3},
    )


def test_purge_image_combines_a_date_and_a_time(run, vm_manager):
    run(
        command="purge_image", name="vm0",
        purge_date={"date": "2026-01-31", "time": "23:45:00"},
    )

    _, _, kwargs = only_call(vm_manager)
    assert kwargs["date"] == datetime.datetime(2026, 1, 31, 23, 45)


def test_purge_image_accepts_an_iso_8601_timestamp(run, vm_manager):
    run(
        command="purge_image", name="vm0",
        purge_date={"iso_8601": "2026-01-31T23:45:00"},
    )

    assert only_call(vm_manager)[2]["date"] == datetime.datetime(
        2026, 1, 31, 23, 45
    )


def test_purge_image_accepts_a_posix_timestamp(run, vm_manager):
    run(command="purge_image", name="vm0", purge_date={"posix": 1769903100})

    assert only_call(vm_manager)[2]["date"] == datetime.datetime.fromtimestamp(
        1769903100
    )


def test_purge_image_ignores_a_purge_date_it_does_not_recognise(run, vm_manager):
    # Neither date/time, iso_8601 nor posix: the purge falls back to the
    # count filter instead of failing.
    run(command="purge_image", name="vm0", purge_date={"epoch": 1769903100})

    assert only_call(vm_manager)[2]["date"] is None


@pytest.mark.parametrize(
    "purge_date",
    [
        {"date": "2026-01-31"},
        {"time": "23:45:00"},
    ],
)
def test_purge_image_requires_date_and_time_together(run, purge_date):
    with pytest.raises(FailJson) as excinfo:
        run(command="purge_image", name="vm0", purge_date=purge_date)

    assert "date and time must be" in excinfo.value.kwargs["msg"]


@pytest.mark.parametrize(
    "purge_date",
    [
        {"date": "2026-01-31", "time": "23:45:00", "posix": 1769903100},
        {"date": "2026-01-31", "time": "23:45:00", "iso_8601": "2026-01-31"},
        {"posix": 1769903100, "iso_8601": "2026-01-31T23:45:00"},
    ],
)
def test_purge_image_rejects_two_ways_of_saying_when(run, purge_date):
    with pytest.raises(FailJson) as excinfo:
        run(command="purge_image", name="vm0", purge_date=purge_date)

    assert "mutually exclusive" in excinfo.value.kwargs["msg"]


# --- pacemaker constraints ------------------------------------------------


def test_define_colocation_passes_the_peers_and_the_strength(run, vm_manager):
    run(
        command="define_colocation", name="vm0",
        colocated_vms=["vm1", "vm2"], strong=True,
    )

    assert only_call(vm_manager) == (
        "add_colocation", ("vm0", "vm1", "vm2"), {"strong": True},
    )


def test_define_colocation_needs_at_least_one_peer(run):
    with pytest.raises(FailJson) as excinfo:
        run(command="define_colocation", name="vm0", colocated_vms=[])

    assert excinfo.value.kwargs["msg"] == "No colocated VM defined"


def test_add_pacemaker_remote_forwards_the_endpoint(run, vm_manager):
    run(
        command="add_pacemaker_remote", name="vm0", remote_name="vm0-remote",
        remote_address="10.0.0.5", remote_port="3121", remote_timeout="60",
    )

    assert only_call(vm_manager) == (
        "add_pacemaker_remote",
        ("vm0", "vm0-remote", "10.0.0.5"),
        {"remote_node_port": "3121", "remote_node_timeout": "60"},
    )


def test_remove_pacemaker_remote_takes_the_vm_name(run, vm_manager):
    run(command="remove_pacemaker_remote", name="vm0")

    assert only_call(vm_manager) == ("remove_pacemaker_remote", ("vm0",), {})


# --- error handling -------------------------------------------------------


def test_rejects_a_command_it_does_not_implement(run):
    with pytest.raises(FailJson) as excinfo:
        run(command="frobnicate", name="vm0")

    assert excinfo.value.kwargs["msg"] == (
        "frobnicate `command` is not implemented yet"
    )


def test_reports_a_vm_manager_failure_with_its_traceback(run, monkeypatch):
    def boom(_name):
        raise RuntimeError("libvirt is unreachable")

    monkeypatch.setattr(cluster_vm.vm_manager, "start", boom, raising=False)

    with pytest.raises(FailJson) as excinfo:
        run(command="start", name="vm0")

    assert excinfo.value.kwargs["msg"] == "libvirt is unreachable"
    assert "RuntimeError" in excinfo.value.kwargs["exception"]


def test_create_carries_the_pinning_profile(run, vm_manager, image):
    profile = "vcpus:\n  isolation: exclusive_physical\n"

    run(command="create", name="vm0", xml="<domain/>", system_image=image,
        pinning_profile=profile)

    assert only_call(vm_manager)[1][0]["pinning_profile"] == profile


def test_clone_carries_the_pinning_profile(run, vm_manager):
    profile = "vcpus:\n  isolation: exclusive_logical\n"

    run(command="clone", name="vm1", src_name="vm0", pinning_profile=profile)

    assert only_call(vm_manager)[1][0]["pinning_profile"] == profile


def test_clone_without_a_profile_lets_vm_manager_copy_the_source_one(
    run, vm_manager
):
    run(command="clone", name="vm1", src_name="vm0")

    assert only_call(vm_manager)[1][0]["pinning_profile"] is None
