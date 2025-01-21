# CentOS Physical Machine Role

This role applies the SEAPATH prerequisites for any Debian physical machine (hypervisor, observer, or standalone).

## Requirements

No requirement.

## Role Variables

| Variable                       | Required  | Type        | Default | Comments                                                                                                                  |
|--------------------------------|-----------|-------------|---------|---------------------------------------------------------------------------------------------------------------------------|
| extra_sysctl_physical_machines | No        | String      |         | Custom systctl configuration separate by new spaces                                                                       |
| extra_kernel_modules           | No        | String list |         | List of Kernel modules to load when booting                                                                               |
| admin_user                     | Yes       | String      |         | Administrator Unix username                                                                                               |
| logstash_server_ip             | No        | String      |         | Address IP of the logstash server                                                                                         |
| pacemaker_shutdown_timeout     | No        | String      | 2min    | Custom timeout for stopping the systemd Pacemaker service. Time is in seconds, but support the min suffix to use minutes. |
| chrony_wait_timeout_sec        | No        | String      | 180     | Custom timeout for stopping the systemd Chrony service. Time is in seconds, but support the min suffix to use minutes.    |
|                                |           |             |         |                                                                                                                           |
| unbind_pci_address             | no        | String list |         | List of PCI addresses to "unbind".                                                                                        |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.centos_physical_machine }
```
