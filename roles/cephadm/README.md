# cephadm Role

This role deploys ceph using cephadm (instead of ceph-ansible)

## Requirements

no requirement.

## Role Variables

| Variable        | Required | Type   | Default      | Comments                                                                              |
|-----------------|----------|--------|--------------|---------------------------------------------------------------------------------------|
| cephadm_install | No       | String | false        | Whether the role will download and install the cephadm binary (true or false)         |
| cephadm_release | No       | String | "19.2.2"     | Version of the cephadm binary to install                                              |
| ceph_spec_path  | No       | String | spec.yaml.j2 | Path to the spec file of cephadm. Use it to override the default config               |
| hostname        | Yes      | String |              | The hostname of the machine. Can be fallback to "inventory_hostname" in the inventory |
| public_network  | Yes      | String |              | Ceph public network.                                                                  |
| cluster_network | Yes      | String |              | SEAPATH cluster network. Will be used as ceph cluster network                         |
| cluster_ip_addr | Yes      | String |              | IP address of the machine on the cluster network                                      |

More information about ceph networks on [ceph documentation](https://docs.ceph.com/en/latest/rados/configuration/network-config-ref/).

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cephadm }
```
