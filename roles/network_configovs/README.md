# network configovs Role

This role configures OVS

## Requirements

No requirement.

## Role Variables

| Variable           | Requiered | Type         | Comments                                                                                                             |
|--------------------|-----------|--------------|----------------------------------------------------------------------------------------------------------------------|
| seapath_distro     | yes       | String       | SEAPATH variant. CentOS, Debian or Yocto. The variable can be set automatically using the detect_seapath_distro role |
| ovs_vsctl_cmds     | no        | String list  | List of custom Open vSwtich commands to run with ovs-vsctl                                                           |
| apply_config       | yes       | Bool         | Set to true to apply Open vSwitch configuration                                                                      |
| interfaces_on_br0  | no        | ???          | TODO                                                                                                                 |
| ovs_bridges        | no        | List of dict | List of Open vSwitch bridges. Refer to for  more details https://github.com/seapath/python3-setup-ovs                |
| ignored_bridges    | no        | String list  | List of OVS bridges to be ignored by this role                                                                       |
| ignored_taps       | no        | String list  | List of tap interface to be ignored by this role                                                                     |
| unbind_pci_address | no        | String list  | List of PCI addresses to "unbind".                                                                                   |

## Example Playbook

```yaml
- name: Configure OVS
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.network_configovs }
```
