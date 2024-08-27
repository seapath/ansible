# Ceph Expansion VG Role

This role extends the ceph VG to whatever is ask in the variables

## Requirements

no requirement.

## Role Variables

- lvm_volumes

## Example Playbook

```yaml
- hosts: osds
  become: true
  gather_facts: yes
  roles:
    - { role: seapath_ansible.ceph_expansion_vg }
```
