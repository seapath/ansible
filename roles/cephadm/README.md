# cephadm Role

This role deploys ceph using cephadm (instead of ceph-ansible)

## Requirements

no requirement.

## Role Variables

| Variable               | Required | Type   | Default      | Comments                                                                              |
|------------------------|----------|--------|--------------|---------------------------------------------------------------------------------------|
| cephadm_release        | No       | String | "20.2.0"     | Version of the cephadm binary to install                                              |
| cephadm_release_name   | No       | String | "tentacle"   | Name of the ceph release, needed for repo installation                                |
| cephadm_downloadbinary | No       | String | false        | whether we install the cephadm by downloading it to /tmp/cephadm                      |
| cephadm_installbinary  | No       | String | false        | whether we install the cephadm binary by copying from /tmp/cephadm to /usr/local/bin  |
| cephadm_installrepo    | No       | String | false        | whether we install the cephadm package with "cephadm add-repo"                        |
| cephadm_installpackage | No       | String | false        | whether we install the cephadm package with "cephadm install"                         |
| cephadm_installcommon  | No       | String | false        | whether we install the ceph-common package with "cephadm install ceph-common"         |
| cephadm_pullimages     | No       | String | false        | whether we pull the needed container images                                           |
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
