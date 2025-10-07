# Yocto Role

This role contains the prerequisites for yocto

## Requirements

No requirement.

## Role Variables

| Variable                  | Roles                     | Required | Type    | Default | Comments                                  |
|---------------------------|---------------------------|----------|---------|---------|-------------------------------------------|
| extra_kernel_parameters   | extra_kernel_parameters   | No       | String  |         | Extra kernel parameter to set             |
| kernel_parameters_restart | kernel_parameters_restart | No       | Bool    | false   | Restart after the kernel parameter update |
| yocto_hugepages           | hugepages                 | No       | Integer | 0       | One GB hugepages to allocate              |
| sriov                     | List of dict | List of network interfaces to configure for SR-IOV use. Dictionary list: `{ interface_name: number_of_interface_to_create }`             |


## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.yocto.kernel_params }

- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.yocto.hugepages }
```
