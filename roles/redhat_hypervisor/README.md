# RedHat Hypervisor Role

This role applies the hypervisor specific configurations (virtualisation, realtime...) for RedHat-family machines

## Requirements

No requirement.

## Role Variables

All variables are optional.

| Variable                  | Type         | Comments                                                                                                                                 |
|---------------------------|--------------|------------------------------------------------------------------------------------------------------------------------------------------|
| isolcpus                  | String       | CPU cores  isolate. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                                             |
| sriov_driver              | String       | Name of the module used for SR-IOV                                                                                                       |
| sriov                     | List of dict | List of network interfaces to configure for SR-IOV use. Dictionary list: `{ interface_name: number_of_interface_to_create }`             |
| cpusystem                 | String       | CPU cores reserved for system's processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                      |
| cpuuser                   | String       | CPU cores reserved for users' processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                        |
| cpumachines               | String       | CPU cores reserved for virtual machines processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10              |
| cpumachinesrt             | String       | CPU cores reserved for real-time virtual machines processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10    |
| cpumachinesnort           | String       | CPU cores reserved for no real-time virtual machines processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10 |
| cpuovs                    | String       | CPU cores reserved open vSwitch processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                      |
| custom_tuned_profile_path | String       | Path in the Ansible machine for custom tuned profile to be used                                                                          |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.redhat_hypervisor }
```
