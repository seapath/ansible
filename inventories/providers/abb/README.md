# ABB Inventory

This directory contains the example inventory files for the SSC600 SW from ABB. It can configure a standalone hypervisor and a SSC600 SW VM.
The VM name must contain the string "ssc600" to be recognized by the qemu hook provided by ABB. (See the files needed section).
The VM deployment has been tested on a Yocto and a Debian hypervisor using the version 1.5.1 of ABB SSC600 SW.

Note: This example is prepared to deploy the VM using an Ansible VM Jinja2 template when all the variable are defined in the Ansible inventory.
It is also possible to deploy the VM using a libvirt XML file directly. If you choose this option you can refer to the ABB documentation:
https://techdoc.relays.protection-control.abb/r/SSC600-and-SSC600-SW-Engineering-Manual/1.5/en-US/VM-configuration.

## Structure

- `ssc600sw_hypervisor_standalone_example.yaml`: The inventory for a standalone hypervisor
- `ssc600sw_vm_example.yaml`: The inventory for the SSC600 VM

## Files needed

Some files provided by ABB are needed to use these inventories:

- ssc600sw\_disk.img.gz
- qemu.hook

To use them, they can be copied in the `files` directory at the root of ansible.

> The raw image disk ssc600sw_disk.img.gz has to be converted to qcow2 format to work on SEAPATH.

This can be done with the following commands:

- `pigz -d ssc600sw_disk.img.gz`
- `qemu-img convert -f raw -O qcow2 ssc600sw_disk.img ssc600sw_disk.qcow2`

*Warning: Both the img.gz and the qcow2 files are less than 1Gib. However, the intermediate `ssc600sw_disk.img` file is 30GiB*

## Prerequisite

The VM need at least 30GB of free space.

* On standalone Ansible deploy it in the /var/lib/libvirt/images directory.

> Make sure to have free 30GB on /var/lib directory

* If you deploy the VM on a SEAPATH cluster the Ceph pool should a have at least 30GB of free spaces.

## Example architecture

The example inventories have been created to run the SSC600 VM using 3 interfaces (on the figure):

- enps0s1: "Rear" interface
- enps0s2: "Process bus" interface
- enps0s3: "Protection communication" interface

![architecture](ssc600sw-example-architecture.png)

## Hypervisor setup

* To fullfill RT requirement the VM must be deployed dedicated on isolated cores.

> isolcpus must be set on the hypervisor inventory.

* The hypervisor must be time synchronized with PTP.

> `ptp_interface` must be defined in the host inventory

* 6 hugepages of 1GB each must be available per VM.

> On Debian add `grub_append: "default_hugepagesz=1G hugepagesz=1G hugepages=6"` on Yocto it can be configured at build time or
with the Ansible variable `yocto_hugepages: 6`.

The file `inventories/providers/abb/ssc600sw_hypervisor_standalone_example.yaml` can be used as hypervisor Ansible inventory example.

## SSC600 SW Ansible inventory

You can use the `inventories/providers/abb/ssc600sw_vm_example.yaml` file as an example to create your custom VM inventory.

Below is a list of all the variables that are supported by this inventory :
* description: The libvirt description of the virtual machine.
* vm_template: The jinja2 xml template to use for the VM. Should be left unchanged.
* vm_disk: The path to the SSC600 SW disk on the deployment machine.
* memory: The number of 1GB hugepages to use. 6GB are necessary for the VM to boot.
* cpuset: A list of the hypervisor CPUs used by the VM. 4 isolated CPUs should be provided.
* emulatorpin: Optional, the host CPU on which to isolate the emulator thread of QEMU. Refer to the [SEAPATH wiki](https://lf-energy.atlassian.net/wiki/spaces/SEAP/pages/31821162/SEAPATH+libvirt+documentation) for more information.
* rt_priority: The priority of the QEMU thread of each vcpu on the host. Should be left unchanged if the VM uses isolated CPUs.
* wait_for_connection: Wait for the VM to be accessible by SSH. Set to false because no ssh session is available on the SSC600 SW.
* bridges: Dictionary of {name, mac_address} to describe VM connection to hypervisor Linux bridges.
* pci_passthrough: list of PCI-passthrough interfaces to pass to the VM. This is the method recommended by ABB for process bus interfaces.
* ovs: a list of tap interfaces on Open vSwitch bridges to connect the VM.

## Cache L3 partitioning

The L3 cache partitioning is not supported and would need to be tested with and without to see the impact.

## Launching the VM

Once the inventory is ready, you can launch the VM using the playbooks deploy_vms_standalone.yaml or deploy_vms_cluster.yaml.

## Access to ABB HMI

Once the VM has booted, the only access referenced in ABB Documentation is through a web HMI accessible on 192.168.2.10/24.
In order for this HMI to be accessible outside of the hypervisor, the br0 bridge must have an IP on this subnet (for example 192.168.2.11).

This can be done either :

- directly in the inventory by setting the IP of your hypervisor `ansible_host: 192.168.2.11`
- by logging into the hypervisor and typing `sudo ip addr add 192.168.2.11/24 dev br0`
