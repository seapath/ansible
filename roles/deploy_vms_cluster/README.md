# Deploy VMs on Cluster Seapath Role

This role deploys a VM in a SEAPATH cluster.

It use the `cluster_vm` Ansible plugin.

Refer to the plugin documentation to know more about this plugin: https://galaxy.ansible.com/ui/repo/published/seapath/ansible/content/module/cluster_vm/

## Requirements

No requirement.

## Role Variables

| Variable                                | Required | Type   | Default | Comments                                                                                 |
|-----------------------------------------|----------|--------|---------|------------------------------------------------------------------------------------------|
| item                                    | Yes      | String |         | Name of the VM to deploy. This VM must be defined in the inventory. See structure below. |
| livemigration                           | No       | String |         | Linux user to use for VM livemigration                                                   |
| deploy_vms_cluster_qcow2tmpuploadfolder | No       | String | "/tmp"  | Hypervisor directory to store VM disks temporarily while VMs are beeing created          |
| deploy_vms_cluster_vms_disks_directory  | No       | String |         | Path in the Ansible machine to be prepend to the disk image path                         |
| deploy_vms_cluster_disk_copy            | No       | Bool   | true    | Set true to copy the VM disk from the Ansible machine before creating the VM             |

The role uses the "VMs" group of the inventory. All members of this group will be deployed according to member's variable described below.
The Ansible member inventory host name will be used as VM name.

| *item* variables   | Required | Type        | Default                               | Comments                                                              |
|--------------------|----------|-------------|---------------------------------------|-----------------------------------------------------------------------|
| vm_disk            | No       | String      | vms_disks_directory + item + ".qcow2" | Path to the VM disk in `qcow2` format on the the Ansible machine      |
| vm_template        | No       | String      |                                       | Path of the VM Libvirt XML templated file on the ansible machine      |
| xml_path           | No       | String      | vms_disks_directory + item + ".qcow2" | Path of the VM Libvirt XML file (non-template) on the ansible machine |
| force              | No       | Bool        | false                                 | Replace the VM if a VM with the same name is already deployed         |
| enable             | No       | Bool        | true                                  | Enable and start the VM after creating it                             |
| nostart            | No       | Bool        | false                                 | Don't start the VM once deployed                                      |
| live_migration     | No       | Bool        | false                                 | Set to true to enable livemigration support for this VM               |
| migrate_to_timeout | No       | Integer     |                                       | Maximum time given to a guest to live migrate (in seconds)            |
| migration_downtime | No       | Integer     |                                       | Allowed downtime when live migrating (in milliseconds)                |
| priority           | No       | Integer     |                                       | Priority of resource in pacemaker                                     |
| pinned_host        | No       | String      |                                       | Pin the VM on the given host. Fail if not possible                    |
| preferred_host     | No       | String      |                                       | Deploy the VM on the given host in priority if possible               |
| crm_config_cmd     | No       | String list |                                       | List of `crm config` to run when enabling this guest                  |
| colocated_vms      | No       | String list |                                       | VM list to be be colocated with the new VM                            |
| strong_colocation  | No       | Bool        | false                                 | Enable strong colocation on colocated_vms. The VM will will not be started when the constraint is not fulfilled |

Here is an example of the structure for the VM inventory:

```yaml
VMs:
  hosts:
    myVM:
      vm_template: "../templates/vm/guest.xml.j2"
      vm_disk: "../files/guest.qcow2"
      force: true
      [...]
```

## Use a templated libvirt XML file

The `vm_template` variable can point toward a jinja2 templated XML file.
If writing your own templated xml file, all the vm member variables are accessible using the `vm` variable. Ex : `"{{ vm.vm_disk }}"`
You can find an example of templated XML file in templates/vm/guest.xml.j2.

### Use the templated XML file guest.xml.j2

This templated XML file offers default behaviors and configurations to launch VMs on SEAPATH. It is mostly used for CI and demonstration on SEAPATH.
It can be a good starting point if you plan to deploy your VM on SEAPATH, however, for any production setup, it is recommended to create your own XML file.
Below is a list of the VMs member variables that can be used with this XML file. None of these variables are required.

| Member variable | Derived variable | Type            | Default | Comments                                                                                                           |
|-----------------|------------------|-----------------|---------|--------------------------------------------------------------------------------------------------------------------|
| uuid            |                  | Integer         | random  | Libvirt UUID of the VM                                                                                             |
| description     |                  | String          | Test VM | Libvirt description of the VM                                                                                      |
| memory          |                  | Integer         | 2048    | RAM of the VM in MiB                                                                                               |
| additional_disk |                  | List of strings |         | Additional disks to give to the VM. The main disk is given by the vm_disk variable                                 |
| vm_features     |                  | List of strings |         | List of vm features to enable. Possible values are "rt", "isolated", "secure-boot", "dpdk", "membaloon"            |
|                 | rt               |                 |         | Enable real time tweaks (priority, cgroup, scheduler, etc ...). Depends on `cpuset`                                |
|                 | isolated         |                 |         | Pin vCPU to hypervisor CPUs. Depends on `cpuset`                                                                   |
|                 | secure-boot      |                 |         | Enable secure boot                                                                                                 |
|                 | dpdk             |                 |         | Connect the VM to a DPDK OVS bridge port. Depends on `dpdk`                                                        |
|                 | memballoon       |                 |         | Enable memory ballooning for the VM.                                                                               |
| cpuset          |                  | List of int     |         | List of hypervisor CPU cores to use in the case of an isolated/RT VM                                               |
| emulatorpin     |                  | Integer         |         | Hypervisor CPU on which to pin the QEMU thread running the VM. If not set, the thread is not pinned.               |
| nb_cpu          |                  | Integer         | 1       | Number of vCPU for the VM. Fallback to `cpuset` size if defined.                                                   |
| sriov           |                  | List of strings |         | List of SRIOV pools to use.                                                                                        |
| pci_passthrough |                  | List of dict    |         | List of dictionaries defining devices to passthrough to the VM. Each entry must contain:                           |
|                 | domain           | Integer         |         | PCI domain of the device                                                                                           |
|                 | bus              | Integer         |         | PCI bus of the device                                                                                              |
|                 | slot             | Integer         |         | PCI slot of the device                                                                                             |
|                 | function         | Integer         |         | PCI function of the device                                                                                         |
| bridges         |                  | List of dicts   |         | List of Linux bridges to use. Each entry must define:                                                              |
|                 | name             | String          |         | Name of the bridge to connect to                                                                                   |
|                 | mac_address      | String          |         | Mac address of the virtual NIC of the VM on this bridge                                                            |
| ovs             |                  | List of dicts   |         | List of OVS ports to use. Each element must contain:                                                               |
|                 | ovs_port         | String          |         | OVS port to use for this interface                                                                                 |
|                 | mad_address      | String          |         | Mac address of this interface                                                                                      |
| dpdk            |                  | List of dicts   |         | List of Open vSwitch ports on which to enable dpdk. Depends on `dpdk` in `vm_features`. Each element must contain: |
|                 | ovs_port         |                 |         | OVS port on which to enable DPDK                                                                                   |
|                 | cpu_nb           |                 |         | Hypervisor CPU to use for this port (100% of the cpu time will be used)                                            |

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
