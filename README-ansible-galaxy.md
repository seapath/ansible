# SEAPATH ansible collection

This collection provides the roles and playbooks to deploy a SEAPATH infrastructure, either in standalone or cluster mode.

The structure of the inventories and the mandatory variables are described in the next section.

Many extension and customization points are available, the associated variables are described in the README of the roles.
The section "Roles" provides a list and description of all the roles available in the collection.

Finally, the "Playbooks" section describe the playbooks provided.
These playbooks cover standard needs and should be sufficient for prototyping or testing with SEAPATH.
For a production usage, we recommend writing your own playbooks, calling only the roles you need.

# Inventory structure

## Physical machines

A single SEAPATH inventory can only handle either a cluster or a standalone setup.
- In case of a cluster setup, the inventory can only describe one cluster of three machines.
- In case of a standalone setup, the inventory can describe multiple standalone machines.

The following groups are used in a SEAPATH inventory

- `all`: Must contains all the machines of the inventory.
- `hypervisors`: The machines to be used as SEAPATH hypervisors

The following group must only be present in case of a standalone setup:
- `standalone_machines`: The machine to be considered as standalone SEAPATH hypervisors.

The following groups must only be present in case of a cluster setup:
- `observers`: The machine to be used as SEAPATH observers. Must be empty (or not present) in case of a cluster with three hypervisors.
- `cluster_machines`: The machines to form the cluster. Must contain three and only three machines.
- `mons`: Machines to use as Ceph monitors. All cluster machines should be part of this group.
- `osds`: Machines to use as Ceph OSD. All hypervisors must be part of this group.
- `clients`: All machines to use the Ceph storage. All cluster machines must be part of this group.

## Virtual machines

To deploy virtual machines on SEAPATH with the deployment playbooks, all VMs must be part of the `VMs` group.
More information on the roles README :
- Deployment on a cluster: https://galaxy.ansible.com/ui/repo/published/seapath/ansible/content/role/deploy_vms_cluster/
- Deployment on a standalone setup: https://galaxy.ansible.com/ui/repo/published/seapath/ansible/content/role/deploy_vms_standalone/

Examples of cluster, standalone, and VMs inventories are available on GitHub: https://github.com/seapath/ansible/tree/main/inventories/examples

Note: On he SEAPATH machine, the user that executes the Ansible commands is called "ansible".

# Roles

This section listed all the roles available in the collection by sections.

Customization and extension variables are available in the README of each role. Remember that the role needs to be called by a playbook to be applied.
You can use default SEAPATH playbooks or write your own.

## Cluster

- `ceph_prepare_installation`: Prepare the disk or LVM volume for Ceph
- `ceph_expansion_lv`: Expand the logical volume used by Ceph OSD
- `ceph_expansion_vg`: Expand the volume group used by Ceph OSD
- `add_livemigration_user`: Configure the user that will perform VM live migration
- `cephadm`: Deploy Ceph on the cluster using cephadm
- `configure_admin_user`: Configure SSH connection for admin user on the cluster
- `configure_ha`: Configure pacemaker and Corosync
- `configure_libvirt`: Create an RBD pool for Libvirt, to be used by the VMs

## Network

- `network_basics`: Remove installation files to prepare proper networking.
- `network_buildhosts`: Build host and hostname files
- `network_clusternetwork`: Configure the cluster network
- `network_configovs`: Create user defined Open vSwitch networks
- `network_netplan`: Configure the machine network using netplan
- `network_systemdnetworkd`: Configure the machine network using systemd-networkd
- `network_networkdwait`: Configure systemd-networkd service
- `network_resolved`: Configure DNS with resolved
- `network_sriovpool`: Create a Libvirt pool for SR-IOV interfaces
- `network_guestsinterfaces`: Create interfaces for VMs that need to be on the administration bridge
- `configure_nic_irq_affinity`: Configure NIC IRQs affinity (useful for macvtap interfaces)
- `conntrackd`: Configure conntrackd
- `iptables`: Load user defined iptables rules

## Time synchronisation

- `timemaster`: Configure time synchronisation with timemaster
- `ptp_status_vsock`: Configure the PTP status socket for VMs

## Virtual machine deployment

- `deploy_vms_cluster`: Deploy all VMs under the `VMs` group on the SEAPATH cluster
- `deploy_vms_standalone`: Deploy all VMs under the `VMs` group on all standalone machines

## Debian specific SEAPATH configuration

All these roles configure the bare Debian distribution for SEAPATH requirements.
They should always be called together. We strongly advise relying on the associated prerequisites playbook to avoid errors.

Note: For the Yocto based SEAPATH, this configuration is done at build time

- `debian`
- `debian_hypervisor`
- `debian_physical_machine`
- `backup_restore`
- `deploy_python3_setup_ovs`
- `deploy_vm_manager`

## Utility roles

- `update`: Update a SEAPATH machine (Yocto only)
- `yocto`: Specify additional kernel parameters and SR-IOV configuration (Yocto only)
- `debian_grub_bootcount`: Setup a rollback system in GRUB (Debian only)
- `deploy_cukinia`: Deploy the testing system on a Debian machine (Debian only)
- `debian_tests`: Launch the system tests on a Debian machine (Debian only)
- `deploy_cockpit_plugins`: Deploy the SEAPATH specific cockpit plugins (Debian only)
- `hardware_customization_welotec`: Configure network cards on the Welotec machines
- `detect_seapath_distro`: Detect the SEAPATH distro base (Debian/Yocto) and set the `seapath_distro` variable.

## Debian hardening

Apply the SEAPATH cybersecurity layer on SEAPATH Debian. On Yocto, this is done at compile time.
This two roles should always be called together, we advise using the `seapath_setup_hardened_debian.yaml` playbook.

- `debian_hardening`
- `debian_hardening_physical_machine`

## Management

- `snmp`: Configure SNMP
- `vmmgrapi`: Configure the vm manager API

## CI roles

All these roles are used only for the SEAPATH CI.
They should be moved in a specific CI collection in a future release.

- `ci_centos`
- `ci_cleanup_varlog`
- `ci_reinstalliso`
- `ci_restoredd`
- `ci_restore_snapshot`
- `ci_yocto`

## Under development

This section concerns roles for under development SEAPATH distributions. They are not described in this README.

- `centos`
- `centos_hypervisor`
- `centos_physical_machine`
- `oraclelinux`
- `oraclelinux_physical_machine`
- `oraclelinux_tests`

# Playbooks

This section lists all the playbooks and their usage. These playbooks call the roles defined above on the associated group of machine.

The main playbook `seapath_setup_main.yaml` should be used to deploy a complete default SEAPATH. It call most of the other playbooks.
This playbook also call many things that you probably don't need. For production, we recommend writing your own playbook by following this model.

The other playbooks can be called alone to re-configure a specific part, when you need to change it.

## Main SEAPATH features

- `seapath_setup_main.yaml`: Deploy a default SEAPATH this playbook call most of the others
- `seapath_setup_network.yaml`: Deploy all SEAPATH networking features
- `seapath_setup_timemaster.yaml`: Deploy SEAPATH time synchronisation feature

## Cluster

- `cluster_setup_ceph.yaml`: Configure Ceph using ceph-ansible
- `cluster_setup_cephadm.yaml`: Configure Ceph using cephadm
- `cluster_setup_ha.yaml`: Configure Corosync and Pacemaker et Corosync
- `cluster_setup_libvirt.yaml`: Create a Ceph RBD pool for libvirt
- `cluster_setup_users.yaml`: Setup admin and livemigration users over the cluster

## VM deployement

- `deploy_vms_cluster.yaml`: Deploy all VMs under the `VMs` group on the SEAPATH cluster
- `deploy_vms_standalone.yaml`: Deploy all VMs under the `VMs` group on a SEAPATH standalone machine

## Prerequisites per distribution

- `seapath_setup_prerequisdebian.yaml`: Apply required SEAPATH modifications to bare Debian machine.
- `seapath_setup_prerequisyocto.yaml`: Call Yocto specific role (configure kernel params + hugepages)
- `seapath_setup_hardened_debian.yaml`: Apply cybersecurity features on Debian
- `seapath_setup_unhardened_debian.yaml`: Remove cybersecurity features on Debian (useful for testing)
- `seapath_setup_prerequiscentos.yaml`: Apply required SEAPATH modification to bare CentOS machine.
- `seapath_setup_prerequisoraclelinux.yaml`: Apply required SEAPATH modification to bare OracleLinux machine.

## Utility

- `replace_machine_remove_machine_cephadm.yaml`: Remove a machine from the cluster when using cephadm.
- `replace_machine_remove_machine_from_cluster.yaml`: Remove a machine on the cluster when using ceph-ansible.
- `seapath_setup_configure_nic_irq_affinity.yaml`: Configure NIC IRQs affinity (useful for macvtap interfaces)
- `seapath_setup_cockpit_plugins.yaml`: Deploy cockpit plugins on the cluster
- `seapath_setup_custom_hardware.yaml`: Apply hardware specific roles
- `purge_ceph.yaml`: Remove the Ceph configuration on the cluster (only used for development)

Note: All the other `replace_machine_*` playbooks are specific parts of the machine replacement scenario.
They should not be called alone.

## Management

- `seapath_setup_snmp.yaml`: Configure SNMP on all machines
- `seapath_setup_vmmgrapi.yaml`: Configure vm-mgr API on all machines

## Update

- `seapath_update_debian.yaml`: Update a Debian machine
- `seapath_update_yocto_cluster.yaml`: Update a Yocto machine in cluster
- `seapath_update_yocto_standalone.yaml`: Update a Yocto standalone machine

## Test

- `test_deploy_cukinia_tests.yaml`: Deploy the tests on all machine (Debian only, on Yocto the tests are natively present)
- `test_run_cukinia.yaml`: Run functional tests and export a CSV.
- `test_run_cukinia-sec.yaml`: Run security tests and export a CSV.

## CI

CI playbooks. These should not be used directly. They should be moved into a different collection in future releases.

- `ci_all_machines_tests.yaml`:
- `ci_centos_test.yaml`
- `ci_configure.yaml`
- `ci_prepare_publisher.yaml`
- `ci_prepare_VMs.yaml`
- `ci_standalone_setup.yaml`
- `ci_test.yaml`
- `ci_vms_standalone_ptp.yaml`
