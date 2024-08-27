# Ceph Expansion LV Role

This role extends the ceph LV to whatever is ask in the variables

## Requirements

no requirement.

## Role Variables

- lvm_volumes

## Example Playbook

```yaml
- hosts: osds
  become: true
  gather_facts: yes
  serial: 1
  roles:
    - { role: seapath_ansible.ceph_expansion_lv }
```
