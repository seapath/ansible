# PTPstatus PTPvsock Role

This role install the ptpstatus / ptpvsock feature

## Requirements

no requirement.

## Role Variables

no variable.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.ptp_status_vsock }
```
