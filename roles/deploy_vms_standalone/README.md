# Deploy VMs on standalone Seapath Role

Deploy all VMs on the inventory group *VMs* on a SEAPATH hypervisor.
This role do not deploy any VM in cluster mode.

## Requirements

No requirement.

## Role Variables

| Variable                                   | Required | Type   | Default                   | Comments                                                                        |
|--------------------------------------------|----------|--------|---------------------------|---------------------------------------------------------------------------------|
| deploy_vms_standalone_qcow2tmpuploadfolder | No       | String | "/tmp"                    | Hypervisor directory to store VM disks temporarily while VMs are beeing created |
| deploy_vms_standalone_disk_pool            | No       | String | "/var/lib/libvirt/images" | Directory to store VM disks on the hypervisor                                   |
| deploy_vms_standalone_disk_copy            | No       | Bool   | true                      | Set true to copy the VM disk from the Ansible machine before created            |

The role uses the "VMs" group of the inventory. All members of this group will be deployed according to member's variable described below.
The Ansible member inventory host name will be used as VM name.

| *member*  variable | Required | Type   | Default | Comments                                                                                                          |
|--------------------|----------|--------|---------|-------------------------------------------------------------------------------------------------------------------|
| vm_disk            | Yes      | String |         | Path to the VM disk in `qcow2` or `img.gz` (raw gzip compressed) format on the Ansible machine                    |
| vm_template        | Yes      | String |         | Path of the VM Libvirt XML file on the ansible machine. Warning, this must be a templated (jinja2) XML file       |
| force              | No       | Bool   | false   | Replace the VM if a VM with the same name is already deployed                                                     |
| disk_extract       | No       | Bool   | false   | Set to true if the disk is in `img.gz` (raw gzip compressed) format                                               |
| enable             | No       | Bool   | true    | Enable and start the VM after creating it                                                                         |

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

The `vm_template` variable point toward a jinja2 templated XML file.
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
| autostart       |                  | Bool            | true    | Set the VM to autostart on hypervisor boot                                                                         |
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
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.deploy_vms_standalone }
```
