# Ceph Prepare Installation Role

This role validates the disks given to Ceph OSDs before the cluster is
deployed with cephadm, and translates deprecated inventory layouts into the
`ceph_osd_disks` list consumed by the `cephadm` role.

## Requirements

no requirement.

## Role Variables

| Variable       | Required | Type            | Comments                                                                     |
|----------------|----------|-----------------|-------------------------------------------------------------------------------|
| ceph_osd_disks | No       | List of strings | Paths of the block devices to give to Ceph, one OSD per entry (see below)    |
| ceph_osd_disk  | No       | String          | Shorthand for a one-element `ceph_osd_disks` list                             |
| lvm_volumes    | No       | List of one dict| **Deprecated** shared-disk layout, kept for backward compatibility (see below) |

### ceph_osd_disks

Each entry is a path to a block device that entirely belongs to Ceph:

- **Whole disks** (recommended): use stable paths such as
  `/dev/disk/by-path/...`. cephadm creates its own LVM layer on the disk.
- **Pre-existing logical volumes**: for setups where Ceph shares a disk with
  the system, create the LV outside of these playbooks (installer, image or
  manually) and list its `/dev/<vg>/<lv>` path here.

The role checks that every listed device exists and does not hold mounted
filesystems or swap, and fails otherwise. Whether a device must be wiped is
decided later by the `cephadm` role: a device hosting an OSD claimed by the
running cluster is never touched, anything else listed here is zapped and
enrolled (see the `cephadm` role README).

### lvm_volumes (deprecated)

When `lvm_volumes` is defined, the role creates the described partition on
`ceph_osd_disk` and the volume group and logical volume on top of it, then
behaves as if `ceph_osd_disks: ["/dev/<data_vg>/<data>"]` had been given.
New inventories should create the volume outside of these playbooks and use
`ceph_osd_disks` instead.

| Variable      | Type    | Comments                                                        |
|---------------|---------|-----------------------------------------------------------------|
| data          | String  | Name of the logical volume to use for the CEPH OSD              |
| data_size     | Integer | Size of the logical volume, default in megabytes                |
| data_vg       | String  | Name of the volume group to use for the CEPH OSD                |
| device_number | Integer | Number of the partition to use in the disk                      |
| device_size   | Integer | Size of the partition                                           |

**Warning**: lvm_volumes must only contain one element in its list.

## Example Playbook

```yaml
- name: Prepare Ceph installation
  hosts:
      cluster_machines
  become: true
  gather_facts: yes
  roles:
    - { role: seapath_ansible.ceph_prepare_installation }
```
