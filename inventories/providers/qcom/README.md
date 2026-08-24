# QCOM Inventory

This directory contains the example inventories for a standalone QCOM
SEAPATH hypervisor and its virtual machines.

## Structure

- `qcom_host.yaml`: standalone hypervisor configuration.
- `qcom_vms.yaml`: virtual machines deployed on the hypervisor.

## Deploying VMs

Use both inventories when deploying or configuring the virtual machines:

```bash
ansible-playbook \
  -i inventories/providers/qcom/qcom_host.yaml \
  -i inventories/providers/qcom/qcom_vms.yaml \
  playbooks/deploy_vms_standalone.yaml
```

Update the network settings, VM IP address, disk image, CPU set, memory, and
MAC address in the inventories before deployment.

## VM Image

The QCOM VM uses this Yocto-generated QCOW2 image:

```text
seapath-guest-efi-test-image-seapath-vm-arm64.rootfs.wic.qcow2
```

Place the image in the repository `files/` directory. The inventory already
references this file through `vm_disk`.
