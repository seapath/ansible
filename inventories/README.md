<!-- Copyright (C) 2020, RTE (http://www.rte-france.com) -->
<!-- Copyright (C) 2024 Savoir-faire Linux, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Inventories directory

On SEAPATH, the definition of our setup must be described inside [Ansible inventories](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html#passing-multiple-inventory-sources).
You have to define your own inventories files which match with your setup.

## SEAPATH inventories examples

In the `examples` directory, you can find some commented and minimal examples of inventories for a standalone and cluster configuration.

It is possible with Ansible to provides [multiple inventories files](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html#passing-multiple-inventory-sources), and we recommend using this feature for complex setup.

All these inventories contain only the minimal variables required to configure and run SEAPATH. For advanced configuration, please refer to the [Ansible configuration](https://lf-energy.atlassian.net/wiki/x/lIblAQ) page on the wiki.

### Cluster inventory : seapath-cluster.yaml

This inventory describes a cluster using two hypervisors and one observer. It is possible to use a three-hypervisor setup by adding a machine into the `hypervisors` section and removing the `observers` part.
TODO : Put link to cluster architecture page on wiki when written

### Standalone inventory : seapath-standalone.yaml

This inventory describes a standalone SEAPATH machine. It contains virtualization and cybersecurity features of SEAPATH, but not the redundancy offered by the cluster.

### OVS inventory : seapath-ovs.yaml

This inventory describes a network Open vSwitch bridge over the cluster. It allows VM to communicate even after a migration toward another hypervisor.
This work is done through the variable `ovs_bridges`, that is passed to [python3-setup-ovs](https://github.com/seapath/python3-setup-ovs) tool.

Note: The same extended network bridge is defined for all hypervisors through the variable `cluster_machines`.

### Virtual machine inventory : seapath-vm-deployement.yaml

This inventory describes the variables to deploy a Virtual machine on a hypervisor or on the cluster. It does not define any variables to configure what is inside the VM.

Two files are required to deploy a virtual machine on SEAPATH :
- A qemu image file (.qcow2, .iso or .img)
- A Libvirt XML configuration file

The VM example inventory uses the template `templates/vm/guest.xml.j2` which aims to be a general purpose VM template for SEAPATH.

If you aim to run virtual machine for production, we recommend proving your own Libvirt XML. Refer to the [Libvirt API documentation](https://libvirt.org/formatdomain.html) for more information.

## Provider examples

You can find in the subdirectory `providers` some example for COTS VM from providers.
