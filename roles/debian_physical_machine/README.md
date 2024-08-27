# Debian Physical Machine Role

This role apply the SEAPATH prerequisites for any physical machine (hypervisor, observer, or standalone)

## Requirements

no requirement.

## Role Variables

- extra_sysctl_physical_machines
- extra_kernel_modules
- admin_user
- logstash_server_ip
- pacemaker_shutdown_timeout
- chrony_wait_timeout_sec

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.debian_physical_machine }
```
