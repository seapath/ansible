# Ceph Expansion LV Role

This role extends the ceph LV to whatever is ask in the variables

## Requirements

No requirement.

## Role Variables

| Variable    | Required | Type         | Comments                                                                                                                                      |
|-------------|----------|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| lvm_volumes | Yes      | List of dict | LVM volumes used for Ceph OSD. Refer to Ceph Ansible documentation: https://docs.ceph.com/projects/ceph-ansible/en/latest/osds/scenarios.html |


## Example Playbook

```yaml
- hosts: osds
  become: true
  gather_facts: yes
  serial: 1
  roles:
    - { role: seapath_ansible.ceph_expansion_lv }
```
