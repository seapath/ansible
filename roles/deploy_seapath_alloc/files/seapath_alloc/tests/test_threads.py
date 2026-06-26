# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

from seapath_alloc.threads import find_qemu_pid
from .conftest import make_proc_qemu


def test_find_qemu_pid_found(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    assert find_qemu_pid("vm", proc) == 1000


def test_find_qemu_pid_absent(tmp_path):
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="other", vcpu_count=1)
    assert find_qemu_pid("vm", proc) is None


def test_find_qemu_pid_no_prefix_collision(tmp_path):
    """"guest=vm" must not match the process of VM "vm2"."""
    proc = make_proc_qemu(tmp_path, pid=2000, vm_name="vm2", vcpu_count=1)
    assert find_qemu_pid("vm", proc) is None


def test_find_qemu_pid_two_vms_sharing_prefix(tmp_path):
    make_proc_qemu(tmp_path, pid=2000, vm_name="vm2", vcpu_count=1)
    proc = make_proc_qemu(tmp_path, pid=1000, vm_name="vm", vcpu_count=1)
    assert find_qemu_pid("vm", proc) == 1000
    assert find_qemu_pid("vm2", proc) == 2000
