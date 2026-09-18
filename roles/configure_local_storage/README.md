# Configure local storage role

This role creates local volumes on a machine: a new partition in the free
space of a disk, formatted either directly or through LVM, and mounted by UUID.

The case it was written for is the SEAPATH Debian ISO, which lays out a 50 GiB
system partition whatever the size of the disk, and leaves the rest of a 1 TB
disk unallocated. Anything that needs local room, such as a staging directory
for backups, a directory of VM images on a standalone machine or a repository
of ISO files, can then be declared in the inventory rather than prepared by
hand on each machine.

For each entry of `configure_local_storage_volumes`, the role:

1. creates a GPT partition after the last partition of the disk, named after
   the entry;
2. when `lvm` is given, makes that partition a PV and adds it to the volume
   group, creating the group if it does not exist, then creates the logical
   volume;
3. creates the file system on the partition or on the logical volume;
4. mounts it on the mount point, by UUID in `/etc/fstab`.

## Only ever adding

Every step looks at what is there first. An entry whose partition, logical
volume, file system and mount already exist changes nothing, and nothing that
exists is ever resized, reformatted or removed. The role refuses, before
writing anything, to:

- partition a disk listed in `ceph_osd_disks`, compared on resolved paths;
- partition anything but a whole disk;
- write a partition table: a disk with an MBR table, or a whole disk file
  system, or any other signature, is refused, because `parted` relabelling a
  disk erases it. A disk with no table and no signature receives a GPT table;
- use a gap between two partitions. Only the space after the last partition
  is used;
- create a partition larger than that free space, or smaller than 1 GiB;
- mount over a directory that is not empty, or over a mount point that holds
  another file system;
- format a device that already holds a different file system.

The partition is recognised on later runs by its GPT name, which is the entry's
`name`. Renaming an entry therefore makes the role look for a new partition.

## Requirements

The `community.general` and `ansible.posix` collections. The machine needs
`parted`, `lvm2` for the LVM layout, and `xfsprogs` for xfs.

## Role Variables

| Variable | Description |
|---|---|
| `configure_local_storage_volumes` | The list of volumes, empty by default. Set it per machine, since disks differ from one machine to the next |

Each entry takes:

| Key | Required | Description |
|---|---|---|
| `name` | yes | The GPT partition name, at most 36 letters, digits, dashes or underscores. It identifies the partition on later runs |
| `disk` | yes | The whole disk to add the partition to. A stable path such as `/dev/disk/by-path/...` is advised |
| `mountpoint` | yes | Absolute path. It is created if it does not exist, and must be empty if it does |
| `size` | no | `100%` (the default) takes all the free space after the last partition. Otherwise a number followed by `M`, `G` or `T`, in binary units: `500G` |
| `fstype` | no | `ext4` (the default) or `xfs` |
| `mount_options` | no | The fstab options, `defaults` by default |
| `lvm.vg` | no | The volume group. When `lvm` is absent the file system goes directly on the partition. An existing group is extended with the new partition and keeps its other PVs |
| `lvm.lv` | with `lvm` | The logical volume, created once and never resized |
| `lvm.size` | no | As `lvcreate` takes it, `100%FREE` by default. Extending an existing group, the default also takes the free space that group already had |

## Example Playbook

```yaml
- hosts: cluster_machines
  become: true
  roles:
    - role: seapath.ansible.configure_local_storage
      vars:
        configure_local_storage_volumes:
          - name: data
            disk: /dev/disk/by-path/pci-0000:00:17.0-ata-1
            lvm:
              vg: vgdata
              lv: data
            mountpoint: /data
          - name: scratch
            disk: /dev/disk/by-path/pci-0000:00:17.0-ata-2
            size: 200G
            fstype: xfs
            mountpoint: /scratch
```

The `seapath_setup_local_storage.yaml` playbook plays the role on every
machine of the inventory.
