# ABB Inventory

This directory contains the example inventory files for the SSC600 SW from ABB. It can configure a standalone hypervisor and a SSC600 SW VM.
The VM name must contain the string "ssc600" to be recognized by the qemu hook provided by ABB. (See the files needed section).
The VM deployment has been tested on a Yocto and a Debian hypervisor using the version 1.5.0 of ABB SSC600 SW.

## Structure

- `ssc600_hypervisor_standalone_example.yaml`: The inventory for a standalone hypervisor
- `ssc600_vm_example.yaml`: The inventory for the SSC600 VM

## Files needed

Some files provided by ABB are needed to use these inventories:
- ssc600\_disk.img.gz
- qemu.hook

To use them, they can be copied in the `files` directory at the root of ansible.

> The raw image disk ssc600\_disk.img.gz has to be converted to qcow2 format to work on SEAPATH.

This can be done with the following commands:
- `gunzip ssc600sw_disk.img.gz`
- `qemu-img convert -f raw -O qcow2 ssc600_disk.img ssc600_disk.qcow2`

*Warning: Both the img.gz and the qcow2 files are less than 1Gib. However, the intermediate `ssc600sw_disk.img` file is 30GiB*

## Prerequisite

The VM need at least 30GB of free space. Ansible deploy it in the /var/lib/libvirt/images directory.
> Make sure to have free 30GB on /var/lib directory

## Example architecture

The example inventories have been created to run the SSC600 VM using 2 interfaces (on the figure):
- enp0s20f0u7: Ansible management, VM HMI, PTP
- enp88s0: SVs

The default br0 bridge is use.

![architecture](ssc600-example-architecture.png)

## Cache L3 partitioning

The L3 cache partitioning is not supported and would need to be tested with and without to see the impact.

## Access to ABB HMI

Once the VM has booted, the only access referenced in ABB Documentation is through a web HMI accessible on 192.168.2.10/24.
In order for this HMI to be accessible outside of the hypervisor, the br0 bridge must have an IP on this subnet (for example 192.168.2.11).

This can be done either :
- directly in the inventory by setting the IP of your hypervisor `ansible_host: 192.168.2.11`
- by logging into the hypervisor and typing `sudo ip addr add 192.168.2.11/24 dev br0`
