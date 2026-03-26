# PTPstatus PTPvsock Role

This role install the ptpstatus / ptpvsock feature

## Requirements

No requirement.

## Role Variables

| Variable                         | Required | Type    | Default | Comments                                                                                                                               |
|----------------------------------|----------|---------|---------|----------------------------------------------------------------------------------------------------------------------------------------|
| ptp_status_vsock_domain_number   | no       | Integer | 0       | PTP domain number. Value from 0 to 255                                                                                                      |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.ptp_status_vsock }
```
