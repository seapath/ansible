# Deploy VMs on Cluster Seapath Role

This role deploys a VM in a SEAPATH cluster.

It use the `cluster_vm` Ansible plugin.

Refer to the plugin documentation to know more about this plugin: https://galaxy.ansible.com/ui/repo/published/seapath/ansible/content/module/cluster_vm/

## Requirements

No requirement.

## Role Variables


| Variable             | Required | Type   | Default | Comments                                                                                                                                |
|----------------------|----------|--------|---------|-----------------------------------------------------------------------------------------------------------------------------------------|
| qcow2tmpuploadfolder | no       | String | "/tmp"  | Path to a directory where the VM disk will be upload before being create. The VM disk file will be removed after being import into Ceph |
| item                 | yes      | String |         | Ansible inventory name of the VM. It will be the name of the VM. Only numbers and letters are allowed                                   |
| vms_disks_directory  | no       | String |         | Path in the Ansible machine to be prepend to the disk image path                                                                        |
| disk_copy            | no       | Bool   | true    | Set true to copy the VM disk from the Ansible machine before creating the VM.                                                           |
| livemigration        | no       | String |         | Linux user to use for VM livemigration.                                                                                                 |

Note the *item* variable must match an machine inside the inventory. This
machine can defined the following variable to change the role behavior:

| *item* variables   | Required | Type        | Default                               | Comments                                                                                                                                                                                                          |
|--------------------|----------|-------------|---------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| vm_disk            | no       | String      | vms_disks_directory + item + ".qcow2" | Path to the VM disk in `qcow2` format on the the Ansible machine                                                                                                                                                  |
| live_migration     | no       | Bool        | false                                 | Set to true to enable livemigration supporting for this VM                                                                                                                                                        |
| migrate_to_timeout | no       | Int         |                                       | Time given to a guest to live migrate (in seconds)                                                                                                                                                                |
| migration_downtime | no       | Int         |                                       | Allowed downtime when live migrating (in milliseconds)                                                                                                                                                            |
| priority           | no       | Int         |                                       | Priority of resource in pacemaker                                                                                                                                                                                 |
| enable             | no       | Bool        | true                                  | Enable and start the VM after creating it                                                                                                                                                                         |
| force              | no       | Bool        | false                                 | Replace the VM if a VM with the same name is already present                                                                                                                                                      |
| pinned_host        | no       | String      |                                       | Pin the VM on the given host. Fail if not possible                                                                                                                                                                |
| preferred_host     | no       | String      |                                       | Deploy the VM on the given host in priority if possible                                                                                                                                                           |
| crm_config_cmd     | no       | String list |                                       | List of `crm config` to run when enabling this guest                                                                                                                                                              |
| xml_path           | no       | String      | vms_disks_directory + item + ".qcow2" | Path in the Ansible machine of the VM libvirt XML configuration                                                                                                                                                   |
| vm_template        | no       | String      |                                       | Path in the Ansible machine of the VM libvirt XML configuration template which will be used to generate the VM configuration. All *item* Ansible variable will accessible in the template using the *vm* variable |
| colocated_vms      | no       | String list |                                       | VM list to be be colocated with the new VM                                                                                                                                                                        |
| strong_colocation  | no       | Bool        | false                                 | Set to true if we want the colocated_vms to be a strong colocation constraint. In this case VM will not be launch if the constraint is not fulfill                                                                |

More information can be found here: https://lf-energy.atlassian.net/wiki/spaces/SEAP/pages/31821162/SEAPATH+libvirt+documentation

## Example Playbook

```yaml

- name: Deploy myVM on the cluster
  hosts: "{{ groups.hypervisors[0] }}"
  vars:
    item: "myVM"
    vms_disks_directory: my_VM_Directory
  roles:
    - seapath_ansible.deploy_vms_cluster

- name: Deploy all VMs on the cluster
  hosts: "{{ groups.hypervisors[0] }}"
  gather_facts: false
  become: true
  tasks:
  - name: Deploy VMs on Cluster Role
    with_items: "{{ groups['VMs'] }}"
    include_role:
      name: seapath_ansible.deploy_vms_cluster
```
