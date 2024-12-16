# CI restore snapshot Role

Add kernel parameters to existing one.

## Requirements

no requirement.

## Role Variables

| Variable                | Required | Type   | Comments                                                              |
|-------------------------|----------|--------|-----------------------------------------------------------------------|
| grub_append             | yes      | String | The kernel parameters to be added.                                    |
| grub_update_command     | no       | String | Command to use for updating grub. If not set it will be autodetected. |

## Example Playbook

```yaml
- name: Add kernel parameters
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.add_kernel_parameters }
```
