# PTPstatus PTPvsock Role

This role install the ptpstatus / ptpvsock feature

## Requirements

No requirement.

## Role Variables

| Variable        | Requiered | Type           | Comments                                                           |
|-----------------|-----------|----------------|--------------------------------------------------------------------|
| container_only  | no        | Bool           | Set this variable to true to disable ptp_status_vsock installation |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.ptp_status_vsock }
```
