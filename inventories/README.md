<!-- Copyright (C) 2020, RTE (http://www.rte-france.com) -->
<!-- Copyright (C) 2024, SFL (https://savoirfairelinux.com) -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Inventories directory

This is the place where you can store your inventories.
We recommend to have 3 kinds of inventories:
- The cluster description inventory, where you will populate the details of your nodes (ip, interface, network details, disks, etc.): a template is provided (seapath_cluster_definition_example.yml)
- The OpenVSwitch topology inventory, where you will describe the different bridges and ports configuration for OVS: a template is provided (seapath_ovstopology_definition_example.yml)
- The VM inventory, where you will describe all variables related to the virtual machine (number of cores, features, ip, network interface, etc.): a template is provided (seapath_vm_definition_example.yml)

## Optionnal variables

You can find concrete examples of the variables in the inventories of this directory. Below are optionnal advanced variables that are not described in the examples.

### Network implementation

```yaml
apply_network_config: true
# If set to true, the OVS and systemd-network configuration will be applied at runtime, without a reboot.
skip_reboot_setup_network: true
# If set to true, the reboot at the end of the network playbook will be skipped. This is useful in the CI to apply all changes done by ansible within the final reboot. However, it can lead to race conditions if the inventory is not handled correctly.
# It must be used with apply_network_config set to false, otherwise the reboot is already avoided.
skip_recreate_team0_config: true
# If set to true, the team0 ovs bridge of the cluster won't be destroyed and recreated by the network playbook.
remove_all_networkd_config: true
# If set to true, the network playbook will start by wiping the /etc/systemd/network/ directory content, this can help cleaning old conflicting files.
# THIS MUST NOT BE USED WITH skip_recreate_team0_config at the same time or the cluster network config won't be recreated.
```
