# Ceph Expansion LV Role

This role extends the ceph LV to whatever is ask in the variables

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type          | Comments                                                           |
|-------------------------|----------|---------------|--------------------------------------------------------------------|
| lvm_volumes             | no       | Array of dict | LVM volumes                                                        |
| -> data_vg              | no       |String         | TODO                                                               |
| -> data                 | no       |String         | TODO                                                               |
| -> data_size            | no       |String         | TODO                                                               |
| ansible_lvm             | no       | Dict          | TODO                                                               |


## Example Playbook

```yaml
- hosts: osds
  become: true
  gather_facts: yes
  serial: 1
  roles:
    - { role: seapath_ansible.ceph_expansion_lv }
```
