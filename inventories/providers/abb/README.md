# ABB Inventory

This directory contains the example inventory files for the SSC600 SW from ABB. It can configure a standalone yocto hypervisor and a SSC600 SW VM.
The VM name must contain the string "ssc600" to be recognized by the qemu hook provided by ABB. (See the files needed section).

## Structure

- `ssc600_hypervisor_standalone_example.yaml`: The inventory for a standalone hypervisor
- `ssc600_vm_standalone_example.yaml`: The inventory for the SSC600 VM

## Files needed

Some files provided by ABB are needed to use these inventories:
- ssc600_disk.img.gz
- qemu.hook

To use them, they can be copied in the `files` directory at the root of ansible.
