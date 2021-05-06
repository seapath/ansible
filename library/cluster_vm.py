#!/usr/bin/env python3

# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

import os
import traceback
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils._text import to_native

ANSIBLE_METADATA = {
    "metadata_version": "1.0",
    "status": ["preview"],
    "supported_by": "community",
}


__metaclass__ = type

DOCUMENTATION = r"""
---
module: cluster_vm

short_description: Manages virtual machines on a SEAPATH cluster

version_added: "2.9"

description: This module manages virtual machines on a SEAPATH cluster.

options:
  name:
    description:
      - name of the guest VM being managed.
      - This option is required unless I(command) is C(list_vms)
    type: str
    aliases:
      - guest
  command:
    description:
      - The action to perform
      - C(create)  Create and start a new VM. Require arguments I(name), I(xml)
        , I(system_image)
      - C(define)  Create a new VM without starting it. Require arguments
        I(name), I(xml), I(system_image)
      - C(remove)  Remove a VM with its data. Require arguments I(name)
      - C(list_vms)  List all the defined VMs in the cluster
      - C(start)  Start or resume a VM. Require arguments I(name)
      - C(status) Get the status of a VM. Require arguments I(name)
      - C(stop)  Gracefully stop a VM. Require arguments I(name)
      - C(clone) Create a VM based on other VM. Require arguments I(name),
        I(src_name)
      - C(enable)  Enable a VM. Require arguments I(name)
      - C(disable)  Disable a VM. Require arguments I(name)
      - C(snapshot_create) Create a snapshot of a VM. Require arguments I(name)
        ,I(snapshot_name)
      - C(snapshot_remove) Delete a snapshot of a VM. Require arguments I(name)
        ,I(snapshot_name)
      - C(snapshot_purge) Delete all snapshot of a VM. Require arguments
        I(name)
      - C(snapshot_rollback) Restore the VM in its previous state using a
        snapshot. Require arguments I(name), I(snapshot_name)
      - C(list_metadata) List all metadatas associated to a VM. Require
        arguments I(name)
      - C(get_metadata) Get the given metadata associated to a VM. Require
        arguments I(name), I(metadata_name)
      - C(set_metadata) Set the given metadata associated to a VM to the
        given value. Require arguments I(name), I(metadata_name),
        I(metadata_value)
    choices: [ create, define, remove, list_vms, start, status, stop,
    clone, snapshot_create,snapshot_remove, snapshot_purge, snapshot_rollback,
    list_metadata, get_metadata, set_metadata, disable, enable]
    type: str
  xml:
    description:
      - Libvirt XML config used if I(command) is C(create) or C(clone)
      - XML document used with the define command.
      - Must be raw XML content using C(lookup). XML cannot be referenced to a
        file.
    type: str
  system_image:
    description:
      The VM system image disk in qcow2 format to import if I(command) is C(
      create)
    type: path
  force:
    description:
      - Force an action to be performed
      - Relevant if I(command) is C(create), C(define), C(clone),
        C(snapshot_create) or C(stop)
    type: boolean
    default: false
  src_name:
    description:
      - name of the VM to clone
      - This option is required if I(command) is C(clone)
    type: str
  snapshot_name:
    description:
      - name of the snapshot
      - This option is required if I(command) is C(snapshot_create),
        C(snapshot_remove)
    type: str
  metadata_name:
    description:
      - name of a metadata
      - This option is required if I(command) is C(get_metadata),
        C(set_metadata)
    type: str
  disk_data_size:
    description:
      - The disk data size to create
      - Use unit suffix K, M or G
      - Leave it empty not to create a data disk
      - This option is optional if I(command) is C(create) or C(define)
    type: str
  metadata_value:
    description:
      - a metadata value
      - This option is required if I(command) is C(set_metadata)
    type: str
requirements:
    - python >= 3.7
    - librbd
    - libvirt
    - vm_manager

author:
    - Mathieu Dupré (mathieu.dupre@savoirfairelinux.com)
    - Albert Babí Oller (albert.babi@savoirfairelinux.com)
"""

EXAMPLES = r"""
# Create and start a VM
- name: Create and start guest0
  cluster_vm:
    name: guest0
    command: create
    system_image: my_disk.qcow2
    disk_data_size: 10G
    xml: "{{ lookup('file', 'my_vm_config.xml', errors='strict') }}"

# Force the creation of a VM without starting it
- name: Create guest1
  cluster_vm:
    name: guest1
    command: define
    system_image: my_disk.qcow2
    force: true
    xml: "{{ lookup('file', 'my_vm_config.xml', errors='strict') }}"

# Remove a VM
- name: Remove guest0
  cluster_vm:
    name: guest0
    command: remove

# List VM
- name: List all VMs
  cluster_vm:
    command: list_vms

# start a VM
- name: start guest0
  cluster_vm:
    name: guest0
    command: start

# stop a VM
- name: stop guest0
  cluster_vm:
    name: guest0
    command: stop

# force stopping (power off) a VM
- name: stop guest0
  cluster_vm:
    name: guest0
    command: stop
    force: true

# enable a VM
- name: enable guest0
  cluster_vm:
    name: guest0
    command: enable

# disable a VM
- name: disable guest0
  cluster_vm:
    name: guest0
    command: disable

# clone a VM
- name: clone guest0 into guest1
  cluster_vm:
    name: guest1
    src_name: guest0
    command: clone

# Create a VM snapshot
- name: create a snapshot of guest0
  cluster_vm:
    name: guest0
    command: snapshot_create
    snapshot_name: snap1

# Delete a VM snapshot
- name: remove snap1 snapshot of guest0
  cluster_vm:
    name: guest0
    command: snapshot_remove
    snapshot_name: snap1

# Remove all snapshots
- name: Remove all snapshots of guest0
  cluster_vm:
    name: guest0
    command: snapshot_purge

# Restore a VM from a snapshot
- name: rollback guest0 into snapshot snap1
  cluster_vm:
    name: guest0
    command: snapshot_rollback
    snapshot_name: snap1

# List metadata stored in a VM
- name: list guest0 metadatas
  cluster_vm:
    name: guest0
    command: list_metadata

# Get the value of a metadata
- name: get metadata test_metadata stored on guest0
  cluster_vm:
    name: guest0
    command: get_metadata
    metadata_name: test_metadata

# Set the value of a metadata
- name: write data on metadata test_metadata stored on guest0
  cluster_vm:
    name: guest0
    command: set_metadata
    metadata_name: test_metadata
    set_metadata: test_data
"""

RETURN = """
# for list_vms command
list_vms:
    description: The list of VMs defined on the remote cluster return by the
                 list_vms command
    type: list
    sample: [
        "guest0",
        "guest1"
    ]
    returned: success
# for status command
status:
    description: The status of the VM, among Starting, Started, Paused, Stopped,
                 Stopping, FAILED, Disabled and Undefined return by
                 the status command
    type: str
    sample: "started"
    returned: success
# for get_metadata command
metadata_value:
    description: The metadata returned by the get_metadata command
    type: str
    sample: "my metadata value"
    returned: success
# for list_metadata command
list_metadata:
    description: The metadata list returned by the list_metadata command
    type: list
    sample: [
        "name",
        "xml",
        "other metadata"
    ]
    returned: success
"""

try:
    import vm_manager
except ImportError:
    HAS_VM_MANAGER = False
else:
    HAS_VM_MANAGER = True

commands_list = [
    "create",
    "remove",
    "start",
    "stop",
    "list_vms",
    "enable",
    "disable",
    "status",
]


def run_module():
    module_args = dict(
        command=dict(type="str", required=True, choices=commands_list),
        name=dict(type="str", required=False),
        xml=dict(type="str", required=False),
        data_size=dict(type="str", required=False),
        force=dict(type="bool", required=False, default=False),
        enable=dict(type="bool", required=False, default=True),
        # Use the action plugin copy to copy the file
        system_image=dict(type="str", required=False),
    )
    result = {}
    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)
    if not HAS_VM_MANAGER:
        module.fail_json(
            msg="The `vm_manager` module is not importable. Check the "
            "requirements."
        )
    args = module.params
    command = args.get("command", None)
    if command != "list_vms":
        vm_name = args.get("name", None)
        if not vm_name:
            module.fail_json(
                msg="`name` is required when `command` is `create`"
            )
    force = args.get("force", False)
    data_size = args.get("data_size", None)
    enable = args.get("enable", True)
    if command == "list_vms":
        try:
            result["list_vms"] = vm_manager.list_vms()
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    elif command == "create":
        vm_config = args.get("xml", None)
        if not vm_config:
            module.fail_json(
                msg="`vm_config` is required when `command` is `create`"
            )
        system_image = args.get("system_image", None)
        if not system_image:
            module.fail_json(
                msg="`system_image` is required when `command` is `create`"
            )
        if not os.path.isfile(system_image):
            module.fail_json(
                msg="`system_image` doesn't exist or is not a file`"
            )

        try:
            vm_manager.create(
                vm_name,
                vm_config,
                system_image,
                data_size=data_size,
                force=force,
                enable=enable,
            )
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    elif command == "remove":
        try:
            vm_manager.remove(vm_name)
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    elif command == "start":
        try:
            vm_manager.start(vm_name)
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    elif command == "stop":
        try:
            vm_manager.stop(vm_name)
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    elif command == "disable":
        try:
            vm_manager.disable_vm(vm_name)
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    elif command == "enable":
        try:
            vm_manager.enable_vm(vm_name)
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    elif command == "status":
        try:
            result["status"] = vm_manager.status(vm_name)
        except Exception as e:
            module.fail_json(msg=to_native(e), exception=traceback.format_exc())
    else:
        module.fail_json(msg="Other `command` is not implemented yet")

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()

