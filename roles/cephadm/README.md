# cephadm Role

This role deploys ceph using cephadm (instead of ceph-ansible)

## Requirements

no requirement.

## Role Variables

| Variable                         | Required | Type    | Default | Comments                                                                                                                               |
|----------------------------------|----------|---------|----------|---------------------------------------------------------------------------------------|
| cephadm_install                  | no       | String  | false    | Whether the role will download and install the cephadm binary (true or false)         |
| cephadm_release                  | no       | String  | "19.2.3" | Version of the cephadm binary to install                                              |
| hostname                         | yes      | String  |          | The hostname of the machine. Can be fallback to "inventory_hostname" in the inventory |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cephadm }
```
