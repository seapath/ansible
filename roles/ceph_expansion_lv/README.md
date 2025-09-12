# Ceph Expansion LV Role

This role extends the ceph LV to the required size.

## Requirements

No requirement.

## Role Variables

| Variable      | Required | Type             | Comments                                                                                |
|---------------|----------|------------------|-----------------------------------------------------------------------------------------|
| lvm_volumes   | No       | List of one dict | LVM volumes to be used for Ceph OSD. To use one entire disk, use ceph_osd_disk variable |
| ceph_osd_disk | No       | String           | Node device disk to use for Ceph OSD. The whole disk will be used.                      |

lvm_volumes structure is a list of one dictionnary. All the variables available on the dictionnary are described as follow.
**Warning** : lvm_volumes must only contain one element it its list. Multiple volumes is not handled by SEAPATH.

| Variable      | Type    | Comments                                                        |
|---------------|---------|-----------------------------------------------------------------|
| data          | String  | Name of the logical volume to use for the CEPH OSD              |
| data_size     | Integer | Size of the logical volume, default in megabytes                |
| data_vg       | String  | Name of the volume group to use for the CEPH OSD                |
| device        | String  | Disk on which the logical volume and volume group are installed |
| device_number | Integer | Number of the partition to use in the disk                      |
| device_size   | Integer | Size of the partition                                           |

Example :

```yaml
lvm_volumes:
  - data: lv_ceph
    data_size: 2000
    data_vg: vg_ceph
    device: /dev/disk/by-path/pci-0000:06:00.0
    device_number: 3
    device_size: 3000
```

## Example Playbook

```yaml
- hosts: osds
  become: true
  gather_facts: yes
  serial: 1
  roles:
    - { role: seapath_ansible.ceph_expansion_lv }
```
