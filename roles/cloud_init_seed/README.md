# Build cloud-init seed Seapath Role

This role builds a [cloud-init NoCloud](https://cloudinit.readthedocs.io/en/latest/reference/datasources/nocloud.html)
seed image for a single VM on the Ansible controller.

The seed image is a small disk holding a filesystem labelled `cidata` and
containing the cloud-init `meta-data`, `user-data` and (optionally)
`network-config` files. When this image is attached to a VM as an extra disk,
cloud-init running inside the guest discovers it (by the `CIDATA` label) and
applies the configuration on first boot.

This role only **builds** the image. Attaching it to the VM is the
responsibility of the calling role (`deploy_vms_cluster` /
`deploy_vms_standalone`), which uploads the seed to the hypervisor and adds it
to the VM disks.

## Requirements

`cloud-localds` (Debian/Ubuntu package `cloud-image-utils`) must be installed on
the Ansible controller.

The base VM image must contain cloud-init for the seed to have any effect.

## Role Variables

| Variable                      | Required | Type   | Default                     | Comments                                                                 |
|-------------------------------|----------|--------|-----------------------------|--------------------------------------------------------------------------|
| cloud_init_seed_vm_name       | Yes      | String |                             | Name of the VM. Used as default `instance-id` and `local-hostname`.      |
| cloud_init_seed_vm            | Yes      | Dict   |                             | `hostvars` of the VM. Must contain a `cloud_init` mapping (see below).   |
| cloud_init_seed_output_dir    | No       | String | `/tmp/seapath_cloud_init`   | Directory on the controller where seed images are built.                 |
| cloud_init_seed_disk_format   | No       | String | `qcow2`                     | Disk format of the generated seed image.                                 |

The role returns the path of the generated seed image (on the controller) in
the `cloud_init_seed_path` fact.

## The `cloud_init` mapping

Define a `cloud_init` mapping on the VM in the inventory to enable cloud-init for
that VM. Every key is passed through as-is to the `#cloud-config` `user-data`,
**except** the following reserved keys:

| Key             | Type   | Comments                                                                                        |
|-----------------|--------|-------------------------------------------------------------------------------------------------|
| `hostname`      | String | Also written to the `meta-data` `local-hostname` (and kept in user-data as a cloud-config key). |
| `instance_id`   | String | `meta-data` instance-id. Defaults to the VM name. Changing it makes cloud-init re-run.          |
| `network`       | Dict   | A NoCloud network-config v2 document (without the `version: 2` header, added automatically).    |
| `user_data_file`| String | Path on the controller to a complete user-data file. When set, the generated user-data keys are ignored and this file is used verbatim. |

Any other key (`users`, `packages`, `runcmd`, `write_files`, `ansible`, `ssh_authorized_keys`, ...)
is a standard cloud-config key and is rendered directly into the user-data.

### Example

```yaml
myvm:
  cloud_init:
    hostname: myvm
    users:
      - name: admin
        sudo: "ALL=(ALL) NOPASSWD:ALL"
        ssh_authorized_keys:
          - "ssh-ed25519 AAAA..."
    packages:
      - qemu-guest-agent
    runcmd:
      - ["systemctl", "enable", "--now", "qemu-guest-agent"]
    network:
      ethernets:
        enp1s0:
          addresses: ["10.0.0.10/24"]
          routes:
            - to: "default"
              via: "10.0.0.1"
          nameservers:
            addresses: ["9.9.9.9"]
    # Run Ansible from within the VM at first boot (cloud-init native module)
    ansible:
      install_method: pip
      pull:
        url: "https://github.com/myorg/myrepo.git"
        playbook_name: site.yml
```
