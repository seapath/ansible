# deploy_cephfs Role

This role deploys the CephFS feature using cephadm

## Requirements

You need to use cephadm and not ceph-ansible to use this feature

## Role Variables

| Variable                      | Required | Type   | Default                                    | Comments                                                                 |
|-------------------------------|----------|--------|--------------------------------------------|--------------------------------------------------------------------------|
| `deploy_cephfs_localdirtoupload` | No       | string | `../inventories_private/cephfs_upload/`     | Local directory on the Ansible controller that will be synchronized to the remote CephFS mount. Can be overridden at playbook, group_vars, host_vars, or CLI. |
| `deploy_cephfs_remotedir`        | No       | string | `/mnt/cephfs/`                              | Destination directory on the remote hosts (CephFS mount point). Files from `deploy_cephfs_localdirtoupload` will be copied here. |

## Example Playbook

```
- hosts: cluster_machines
  roles:
    - role: seapath_ansible.deploy_cephfs
      vars:
        deploy_cephfs_localdirtoupload: "/path/to/my/local/data/"
        deploy_cephfs_remotedir: "/mnt/cephfs/"
```
