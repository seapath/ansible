# Deploy VMs on Cluster Seapath Role

This role deploys a VM in a SEAPATH cluster.

It use the `cluster_vm` Ansible plugin.

Refer to the plugin documentation to know more about this plugin: https://galaxy.ansible.com/ui/repo/published/seapath/ansible/content/module/cluster_vm/

## Requirements

No requirement.

## Role Variables

| Variable                                | Required | Type   | Default                 | Comments                                                                                 |
|-----------------------------------------|----------|--------|-------------------------|------------------------------------------------------------------------------------------|
| item                                    | Yes      | String |                         | Name of the VM to deploy. This VM must be defined in the inventory. See structure below. |
| livemigration_user                      | No       | String |                         | Linux user to use for VM livemigration                                                   |
| deploy_vms_cluster_qcow2tmpuploadfolder | No       | String | "/tmp"                  | Hypervisor directory to store VM disks temporarily while VMs are beeing created          |
| deploy_vms_cluster_vms_disks_directory  | No       | String |                         | Path in the Ansible machine to be prepend to the disk image path                         |
| deploy_vms_cluster_disk_copy            | No       | Bool   | true                    | Set true to copy the VM disk from the Ansible machine before creating the VM             |
| deploy_vms_cluster_guests               | No       | List   | `cluster_VMs`, or `VMs` | The guests `deploy_vms_cluster.yaml` loops over. See below                               |

The role uses the "VMs" group of the inventory. All members of this group will be deployed according to member's variable described below.
The Ansible member inventory host name will be used as VM name.

### Which guests the role deploys

The role deploys the members of the `VMs` group. When one inventory holds both
a cluster and a standalone machine, declare `cluster_VMs` and `standalone_VMs`
as children of `VMs` to say which guest belongs to which deployment:

```yaml
VMs:
  children:
    cluster_VMs:
      hosts:
        myClusterVM:
          vm_template: "../templates/vm/guest.xml.j2"
          vm_disk: "../files/guest.qcow2"
    standalone_VMs:
      hosts:
        myLocalVM:
          vm_template: "../templates/vm/guest.xml.j2"
          vm_disk: "../files/guest.qcow2"
```

Ansible lists the hosts of a child group under the parent, so `groups['VMs']`
stays the union of both and the plays that configure the guests themselves
(`seapath_setup_main.yaml`, `seapath_setup_hardening.yaml`) are unchanged. A
flat `VMs` group with no children behaves as before: the role falls back to the
whole group.

| *item* variables   | Required | Type        | Default                               | Comments                                                                                                                                                                                                                                      |
|--------------------|----------|-------------|---------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| vm_disk            | No       | String      | vms_disks_directory + item + ".qcow2" | Path to the VM disk in `qcow2` format on the Ansible machine, or a URL (`http`/`https`/`ftp`/`ftps`) fetched directly on the target. A URL requires `vm_disk_checksum`.                                                                       |
| vm_disk_checksum   | No       | Dict        |                                       | Dict `{<algo>: <hex>, ...}` to verify the system disk after staging. Required when `vm_disk` is a URL, optional for a local path. May list multiple algorithms; the strongest available is used (preference: `sha512` > `sha384` > `sha256`). |
| vm_template        | No       | String      |                                       | Path of the VM Libvirt XML templated file on the ansible machine                                                                                                                                                                              |
| xml_path           | No       | String      | vms_disks_directory + item + ".qcow2" | Path of the VM Libvirt XML file (non-template) on the ansible machine                                                                                                                                                                         |
| force              | No       | Bool        | false                                 | Replace the VM if a VM with the same name is already deployed                                                                                                                                                                                 |
| enable             | No       | Bool        | true                                  | Enable and start the VM after creating it                                                                                                                                                                                                     |
| nostart            | No       | Bool        | false                                 | Don't start the VM once deployed                                                                                                                                                                                                              |
| live_migration     | No       | Bool        | false                                 | Set to true to enable livemigration support for this VM                                                                                                                                                                                       |
| migrate_to_timeout | No       | Integer     |                                       | Maximum time given to a guest to live migrate (in seconds)                                                                                                                                                                                    |
| migration_downtime | No       | Integer     |                                       | Allowed downtime when live migrating (in milliseconds)                                                                                                                                                                                        |
| priority           | No       | Integer     |                                       | Priority of resource in pacemaker                                                                                                                                                                                                             |
| pinned_host        | No       | String      |                                       | Pin the VM on the given host. Fail if not possible                                                                                                                                                                                            |
| preferred_host     | No       | String      |                                       | Deploy the VM on the given host in priority if possible                                                                                                                                                                                       |
| crm_config_cmd     | No       | String list |                                       | List of `crm config` to run when enabling this guest                                                                                                                                                                                          |
| colocated_vms      | No       | String list |                                       | VM list to be be colocated with the new VM                                                                                                                                                                                                    |
| strong_colocation  | No       | Bool        | false                                 | Enable strong colocation on colocated_vms. The VM will will not be started when the constraint is not fulfilled                                                                                                                               |
| disk_bus           | No       | String      |                                       | Disk bus type to use for the VM's disk (virtio, sata, scsi, ide, etc.)                                                                                                                                                                        |

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

The same VM with its disk fetched from a remote location instead (`vm_disk_checksum` is mandatory here):

```yaml
VMs:
  hosts:
    myVM:
      vm_template: "../templates/vm/guest.xml.j2"
      vm_disk: "https://images.example.com/seapath/guest.qcow2"
      vm_disk_checksum:
        sha256: "<sha256 hex digest of guest.qcow2>"
      additional_disk:
        - "../files/data.qcow2"
        - path: "https://images.example.com/seapath/data2.qcow2"
          sha256: "<sha256 hex digest of data2.qcow2>"
      force: true
      [...]
```

## Configure the guest with cloud-init

A VM can be configured on first boot with [cloud-init](https://cloudinit.readthedocs.io/)
by adding a `cloud_init` mapping to its inventory entry. When present, this role
builds a NoCloud seed image (via the `cloud_init_seed` role) and attaches it to
the VM as an extra disk; cloud-init inside the guest applies it on first boot.

Requirements:
- The base VM image must ship cloud-init.
- `cloud-localds` (Debian/Ubuntu package `cloud-image-utils`) must be installed
  on the Ansible controller.

Every key of the `cloud_init` mapping is passed through as a `#cloud-config`
`user-data` key, except the reserved keys `hostname`, `instance_id`, `network`
and `user_data_file`. See the `cloud_init_seed` role README for the full
reference and an example.

## Use a templated libvirt XML file

The `vm_template` variable can point toward a jinja2 templated XML file.
If writing your own templated xml file, all the vm member variables are accessible using the `vm` variable. Ex : `"{{ vm.vm_disk }}"`
You can find an example of templated XML file in templates/vm/guest.xml.j2.

### Use the templated XML file guest.xml.j2

This templated XML file offers default behaviors and configurations to launch VMs on SEAPATH. It is mostly used for CI and demonstration on SEAPATH.
It can be a good starting point if you plan to deploy your VM on SEAPATH, however, for any production setup, it is recommended to create your own XML file.
Below is a list of the VMs member variables that can be used with this XML file. None of these variables are required.

| Member variable | Derived variable | Type            | Default   | Comments                                                                                                                                                                                                                                                                                                                         |
|-----------------|------------------|-----------------|-----------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| uuid            |                  | Integer         | random    | Libvirt UUID of the VM                                                                                                                                                                                                                                                                                                           |
| description     |                  | String          | Test VM   | Libvirt description of the VM                                                                                                                                                                                                                                                                                                    |
| memory          |                  | Integer         | 2048      | RAM of the VM in MiB                                                                                                                                                                                                                                                                                                             |
| additional_disk |                  | List            |           | Additional disks to give to the VM. Each entry is either a path string, or a dict with `path` plus optional checksum keys (`sha512`/`sha384`/`sha256`). A `path` that is a URL (`http`/`https`/`ftp`/`ftps`) is fetched directly on the target and requires a checksum. Device names (vdb, vdc, ...) are assigned automatically. |
| vm_features     |                  | List of strings |           | List of vm features to enable. Possible values are "rt", "isolated", "secure-boot", "dpdk", "memballoon", "graphic-console", "windows"                                                                                                                                                                                           |
|                 | rt               |                 |           | Enable real time tweaks (priority, cgroup, scheduler, etc ...). Depends on `cpuset`                                                                                                                                                                                                                                              |
|                 | isolated         |                 |           | Pin vCPU to hypervisor CPUs. Depends on `cpuset`                                                                                                                                                                                                                                                                                 |
|                 | secure-boot      |                 |           | Enable secure boot. Works only with EFI firmware                                                                                                                                                                                                                                                                                 |
|                 | dpdk             |                 |           | Connect the VM to a DPDK OVS bridge port. Depends on `dpdk`                                                                                                                                                                                                                                                                      |
|                 | memballoon       |                 |           | Enable memory ballooning for the VM.                                                                                                                                                                                                                                                                                             |
|                 | graphic-console  |                 |           | Add a graphic console (VNC) with video and tablet input to the VM                                                                                                                                                                                                                                                                |
|                 | windows          |                 |           | Tune the VM for a Windows guest: Hyper-V enlightenments, `hypervclock` and an explicit CPU topology. With `rt`, the `<cpu>` element comes from `rt`                                                                                                                                                                              |
| legacy_bios     |                  | Bool            | false     | Use legacy BIOS firmware instead of EFI                                                                                                                                                                                                                                                                                          |
| graphics_listen |                  | String          | 127.0.0.1 | Address on which the VNC server listens. Depends on `graphic-console` in `vm_features`                                                                                                                                                                                                                                           |
| cpuset          |                  | List of int     |           | List of hypervisor CPU cores to use in the case of an isolated/RT VM                                                                                                                                                                                                                                                             |
| emulatorpin     |                  | Integer         |           | Hypervisor CPU on which to pin the QEMU thread running the VM. If not set, the thread is not pinned.                                                                                                                                                                                                                             |
| nb_cpu          |                  | Integer         | 1         | Number of vCPU for the VM. Fallback to `cpuset` size if defined.                                                                                                                                                                                                                                                                 |
| sriov           |                  | List of strings |           | List of SRIOV pools to use.                                                                                                                                                                                                                                                                                                      |
| pci_passthrough |                  | List of dict    |           | List of dictionaries defining devices to passthrough to the VM. Each entry must contain:                                                                                                                                                                                                                                         |
|                 | domain           | Integer         |           | PCI domain of the device                                                                                                                                                                                                                                                                                                         |
|                 | bus              | Integer         |           | PCI bus of the device                                                                                                                                                                                                                                                                                                            |
|                 | slot             | Integer         |           | PCI slot of the device                                                                                                                                                                                                                                                                                                           |
|                 | function         | Integer         |           | PCI function of the device                                                                                                                                                                                                                                                                                                       |
|                 | guest_address    | Dict            |           | Optional guest address. `bus` selects the pcie-root-port to attach to, pinning where the guest sees the device across redeploys.                                                                                                                                                                                                 |
| bridges         |                  | List of dicts   |           | List of Linux bridges to use. Each entry must define:                                                                                                                                                                                                                                                                            |
|                 | name             | String          |           | Name of the bridge to connect to                                                                                                                                                                                                                                                                                                 |
|                 | mac_address      | String          |           | Mac address of the virtual NIC of the VM on this bridge                                                                                                                                                                                                                                                                          |
|                 | rx_queue_size    | Integer         |           | Size of virtio receive ring for each queue (optional)                                                                                                                                                                                                                                                                            |
|                 | guest_address    | Dict            |           | Optional guest address, same keys as in `pci_passthrough`. Pins the NIC's pcie-root-port so the guest keeps its adapter identity.                                                                                                                                                                                                |
| ovs             |                  | List of dicts   |           | List of OVS ports to use. Each element must contain:                                                                                                                                                                                                                                                                             |
|                 | ovs_port         | String          |           | OVS port to use for this interface                                                                                                                                                                                                                                                                                               |
|                 | mac_address      | String          |           | Mac address of this interface                                                                                                                                                                                                                                                                                                    |
|                 | rx_queue_size    | Integer         |           | Size of virtio receive ring for each queue (optional)                                                                                                                                                                                                                                                                            |
| dpdk            |                  | List of dicts   |           | List of Open vSwitch ports on which to enable dpdk. Depends on `dpdk` in `vm_features`. Each element must contain:                                                                                                                                                                                                               |
|                 | ovs_port         |                 |           | OVS port on which to enable DPDK                                                                                                                                                                                                                                                                                                 |
|                 | cpu_nb           |                 |           | Hypervisor CPU to use for this port (100% of the cpu time will be used)                                                                                                                                                                                                                                                          |

#### Windows guests

`windows` in `vm_features` enables the Hyper-V enlightenments and `hypervclock`, which
let the guest read time from the Hyper-V reference TSC page instead of trapping out to
the ACPI PM timer, and it declares an explicit CPU topology. Without one libvirt gives
each vCPU its own socket, and Windows client editions cap the socket count at two, so
the remaining vCPUs stay unused. `hypervclock` requires `<hyperv mode="custom">`, and
`migratable="on"` keeps live migration available by excluding `invtsc`. `rt` and
`windows` can be set together: the enlightenments and `hypervclock` still apply, and
only the `<cpu>` element comes from `rt`. That definition omits `migratable="on"`, so
the virtual CPU may keep features that block live migration.

#### Pinning a device to a fixed guest PCI address

`guest_address.bus` names the `pcie-root-port` a device attaches to. libvirt and QEMU
use a device's `bus` value only to match it with the controller carrying the same
`index`, never as an address in its own right, so `bus: "0x06"` reads as "attach to
controller index 6" — it is not the bus number the guest firmware later enumerates.
The value is read as hexadecimal, like `slot` and `function`, and rendered back in the
canonical `0x` form, so `"10"` names port 16 and not port 10. The template declares
that controller with an explicit address:

    slot     = 2 + (index - 1) // 8
    function = (index - 1) % 8

Eight root ports fit in a slot, so index 6 is `00:02.5`, index 8 is `00:02.7` and
index 9 rolls over to `00:03.0`. The mapping is one to one and independent of
everything else in the VM, which is especially important on Windows: device identity
in the guest depends on this parent address. A Windows PCI instance ID ends in the
parent's DevFn, `(slot << 3) | function`, so `00:02.5` yields `…&0&0015`.

Left unpinned, libvirt hands out the next free root port at define time, and adding
or removing any other device re-parents everything after it. A passed-through serial
card then looks like new hardware and its COM ports are renumbered; a virtual NIC
loses the network configuration bound to it.

The bus number the guest reports is not pinned by this and stays firmware-assigned —
a legacy-PCI bridge, such as the one the `i6300esb` watchdog pulls in, shifts it.

**WARNING:** Only PCIe devices can be pinned. A legacy-PCI device does not fit into a
`pcie-root-port` at all: libvirt inserts a `pcie-to-pci-bridge` for it and bumps the
requested bus number by one while doing so, so a pin on such a device silently does
not hold.

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
