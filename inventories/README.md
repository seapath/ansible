<!-- Copyright (C) 2020, RTE (http://www.rte-france.com) -->
<!-- Copyright (C) 2024 Savoir-faire Linux, Inc. -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Inventories directory

On SEAPATH, the definition of our setup must be described inside [Ansible inventories](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html#passing-multiple-inventory-sources).
You have to define your own inventories files which match with your setup.

In this directory, you can find some commented examples of inventories for the following case:
* a SEAPATH cluster demo which can be used to easily test SEAPATH with retails machines (use it as a POC, not in production)
* a SEAPATH standalone hypervisor setup
* a complex SEAPATH cluster

It is possible with Ansible to provides [multiple inventories files](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html#passing-multiple-inventory-sources), and we recommend using this feature for complex setup. In this directory, we have separated the "complex SEAPATH cluster" into three inventories. We have a dedicated inventory file for:
* the physical machines
* the cluster internal network (Open vSwitch topology)
* the virtual machines
## SEAPATH Ansible inventories examples description

All inventories examples are in YAML format. The example inventories are:
* `seapath_demo_cluster_definition_example.yml`: SEAPATH cluster demo
* `seapath_standalone_definition_example.yml`: SEAPATH standalone hypervisor setup
* The complex SEAPATH cluster inventories are:
	* `seapath_cluster_definition_example.yml`: physical machines
	* `seapath_ovstopology_definition_example.yml`: cluster internal network (Open vSwitch topology)
	* `seapath_vm_definition_example.yml`: virtual machines

The directory also contains the firewall rules `iptables_rules_example.txt` which are referring in `seapath_cluster_definition_example.yml`.

The simple SEAPATH cluster inventory require only minor tweak to be adapted. In all other files described, all the options which do not match a realistic case and need to be modified are indicated.

### Optional variables

You can find concrete examples of the variables in the inventories of this directory. Below are optional advanced variables that are not described in the examples.

#### Network implementation

```yaml
apply_network_config: true
# If set to true, the OVS and systemd-network configuration will be applied at runtime, without a reboot.
skip_reboot_setup_network: true
# If set to true, the reboot at the end of the network playbook will be skipped. This is useful in the CI to apply all changes done by ansible within the final reboot. However, it can lead to race conditions if the inventory is not handled correctly.
# It must be used with apply_network_config set to false, otherwise the reboot is already avoided.
skip_recreate_team0_config: true
# If set to true, the team0 ovs bridge of the cluster won't be destroyed and recreated by the network playbook.
remove_all_network_config: true
# If set to true, the network playbook will start by wiping the /etc/netplan/ directory content, this can help cleaning old conflicting files.
# THIS MUST NOT BE USED WITH skip_recreate_team0_config at the same time or the cluster network config won't be recreated.
```

### SEAPATH demo cluster inventory

If you are SEAPATH newcomer, you can use this example to create a SEAPATH POC cluster. At the opposite of a real SEAPATH cluster, which requires an advance machine with multiple cores and network cards. This example only requires one network interface and can be made with costumer retail machines.

Of course, to achieve this, some concessions have been made. We keep only one network, as described in the schema below. Some advanced features have been removed.

<img src="./basic_cluster.png" alt="Exemple d'image" style="max-width:400px">

#### ⚠ SEAPATH demo cluster inventory unsupported features ⚠

- Low latency network
- Dedicated cluster network with redundancy
- Advanced features like:
    - SNMP
    - Syslog log sending
    - Advanced isolation


#### Variables to be configured to use the SEAPATH demo :

You have to change some variables (mainly network settings) to adjust the inventory to your configuration:

- ansible_host for each node (identical to the IP of the switch interface)
- ceph_osd_disk to locate the disk used
- (Optional) data_size and device_size can be modified depending on the space left on the ceph_osd_disk
- gateway_addr
- dns_servers
- ntp_servers
- public_network
- admin_passwd
- admin_ssh_keys
