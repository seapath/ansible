# Ceph Prepare Installation Role

This role prepares the ceph installation by identifying if it's a new install and then prepare the disks

## Requirements

no requirement.

## Role Variables

| Variable      | Required | Type         | Comments                                                                                                                                      |
|---------------|----------|--------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| lvm_volumes   | No       | List of dict | LVM volumes used for Ceph OSD. Refer to Ceph Ansible documentation: https://docs.ceph.com/projects/ceph-ansible/en/latest/osds/scenarios.html |
| ansible_lvm   | No       | Dict         | TODO                                                                                                                                          |
| ceph_osd_disk | No       | String       | Node device disk to use for Ceph OSD if lvm_volumes is not used                                                                               |


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
