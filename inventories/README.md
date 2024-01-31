// Copyright (C) 2020, RTE (http://www.rte-france.com)
// SPDX-License-Identifier: CC-BY-4.0

Inventories directory
=====================

This is the place where you can store your inventories.
We recommend to have 3 kinds of inventories:
- The cluster description inventory, where you will populate the details of your nodes (ip, interface, network details, disks, etc.): a template is provided (seapath_cluster_definition_example.yml)
- The OpenVSwitch topology inventory, where you will describe the different bridges and ports configuration for OVS: a template is provided (seapath_ovstopology_definition_example.yml)
- The VM inventory, where you will describe all variables related to the virtual machine (number of cores, features, ip, network interface, etc.): a template is provided (seapath_vm_definition_example.yml)
