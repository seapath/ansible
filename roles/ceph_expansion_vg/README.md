# Ceph Expansion VG Role

This role extends the ceph VG to whatever is ask in the variables

## Requirements

No requirement.

## Role Variables

| Variable    | Required | Type         | Comments                                                                                                                                      |
|-------------|----------|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| lvm_volumes | No       | List of dict | LVM volumes used for Ceph OSD. Refer to Ceph Ansible documentation: https://docs.ceph.com/projects/ceph-ansible/en/latest/osds/scenarios.html |


## Example Playbook

```yaml
- hosts: osds
  become: true
  gather_facts: yes
  roles:
    - { role: seapath_ansible.ceph_expansion_vg }
```
