# cephadm Role

This role provisions the Ceph cluster using cephadm. Installation of the cephadm binary, prerequisites (users, groups, sudo), image pulling, and registry setup is handled by the `cephadm_install` role.

## Requirements

The `cephadm_install` role must have been applied to `cluster_machines` before this role runs.

## Role Variables

| Variable               | Required | Type   | Default      | Comments                                                                              |
|------------------------|----------|--------|--------------|---------------------------------------------------------------------------------------|
| cephadm_release        | No       | String | "20.2.0"     | Version of the ceph container image                                                   |
| cephadm_spec_path      | No       | String | spec.yaml.j2 | Path to the spec file of cephadm. Use it to override the default config               |
| cephadm_network        | Yes      | String |              | Ceph network (e.g. "192.168.55.0/24")                                                 |

Note that for each node you want in the cluster, those host vars need to be defined:

| Variable               | Required | Type   | Comments                                                                              |
|------------------------|----------|--------|---------------------------------------------------------------------------------------|
| hostname               | Yes      | String | The hostname of the machine. Can be fallback to "inventory_hostname" in the inventory |
| cluster_ip_addr        | Yes      | String | IP address of the machine on the cluster network                                      |

More information about ceph networks on [ceph documentation](https://docs.ceph.com/en/latest/rados/configuration/network-config-ref/).

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cephadm }
```
