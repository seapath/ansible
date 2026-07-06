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

## OSD volume handling

Before adding OSDs, the role decides for each OSD volume whether it must be
wiped, using a single rule: **a volume is kept untouched if and only if it
hosts an OSD claimed by the running cluster** (the OSD uuid stored in the LVM
tags written by ceph-volume is registered in the cluster OSD map). Any other
volume listed for Ceph is zapped and enrolled as a new OSD.

Consequences:

- Re-running the playbook on a live cluster never touches existing OSDs.
- Reinstalling a cluster from scratch (new fsid, empty OSD map) automatically
  wipes and re-enrolls volumes containing data from the previous installation.
- A replaced machine has its volume re-enrolled without manual cleanup.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.cephadm }
```
