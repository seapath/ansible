# Ceph Prepare Installation Role

This role prepares the ceph installation by identifying if it's a new install and then prepare the disks

## Requirements

no requirement.

## Role Variables

- ceph_osd_disk
- lvm_volumes

## Example Playbook

```yaml
- name: Prepare Ceph installation
  hosts:
      osds
  become: true
  gather_facts: yes
  roles:
    - { role: seapath_ansible.ceph_prepare_installation }
```
