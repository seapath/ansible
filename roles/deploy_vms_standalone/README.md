# Deploy VMs on standalone Seapath Role

Deploy all VMs on the inventory group *VMs* on a SEAPATH hypervisor.
This role do not deploy any VM in cluster mode.

## Requirements

No requirement.

## Role Variables

| Variable             | Required | Type   | Default                   | Comments                                                                                                                                     |
|----------------------|----------|--------|---------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| qcow2tmpuploadfolder | no       | String | "/tmp"                    | Path to a directory where the VM's disks will be upload before being create. VM's disks file will be removed after being import into libvirt |
| disk_pool            | no       | String | "/var/lib/libvirt/images" | Disks path on the hypervisor                                                                                                                 |
| disk_copy            | no       | Bool   | true                      | Set true to copy the VM disk from the Ansible machine before creating the VM                                                                 |

The role uses the "VMs" group in the inventory. All members of this group will be deployed according to member's variable described below.
The Ansible member inventory host name will be used as VM name.

| *member*  variable | Required | Type   | Default | Comments                                                                                                                                                                                                         |
|--------------------|----------|--------|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| force              | no       | Bool   | false   | Replace the VM if a VM with the same name is already present                                                                                                                                                     |
| vm_disk            | yes      | String |         | Path to the VM disk in `qcow2` or `img.gz` (raw gzip compressed) format on the Ansible machine                                                                                                                   |
| disk_extract       | no       | Bool   | false   | Set to true if the disk is in `img.gz` (raw gzip compressed) format                                                                                                                                              |
| vm_template        | yes      | String |         | ath in the Ansible machine of the VM libvirt XML configuration template which will be used to generate the VM configuration. All *item* Ansible variable will accessible in the template using the *vm* variable |
| enable             | no       | Bool   | true    | Enable and start the VM after creating it                                                                                                                                                                        |


## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.deploy_vms_standalone }
```
