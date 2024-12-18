# Debian Physical Machine Role

This role apply the SEAPATH prerequisites for any physical machine (hypervisor, observer, or standalone).

## Requirements

No requirement.

## Role Variables

| Variable                       | Type        | Comments                                                                                                                             |
|--------------------------------|-------------|--------------------------------------------------------------------------------------------------------------------------------------|
| extra_sysctl_physical_machines | String      | Custom systctl configuration separate by new spaces                                                                                  |
| extra_kernel_modules           | String list | List of Kernel modules to load when booting                                                                                          |
| admin_user                     | String      | Administrator Unix username                                                                                                          |
| logstash_server_ip             | String      | Address IP of the logstash server                                                                                                    |
| pacemaker_shutdown_timeout     | String      | Custom timeout for stopping the systemd Pacemaker service. Time is a seconds, but support the min suffix to use minutes.Default 2min |
| chrony_wait_timeout_sec        | String      | Custom timeout for stopping the systemd Chrony service. Time is a seconds, but support the min suffix to use minutes.Default 180     |


## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_physical_machine }
```
