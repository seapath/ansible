# Deploy VMs on Cluster Seapath Role

This role deploys Guests in cluster mode

## Requirements

no requirement.

## Role Variables

the role uses the "VMs" group in the inventory
and the following variables:
- qcow2tmpuploadfolder

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.deploy_vms_cluster }
```
