# Network Basics Role

This role builds the host and hostname files.

## Requirements

No requirement.

## Role Variables

| Variable        | Required  | Type   | Comments                                                        |
|-----------------|-----------|--------|-----------------------------------------------------------------|
| hostname        | No        | String | Machine hostname. Default is Ansible inventory_hostname         |
| ip_addr         | Yes       | String | Administration network interface IP address                     |
| cluster_ip_addr | Yes       | String | Cluster network interface IP address                            |
| hosts_path      | No        | String | Path on the Ansible machine to a custom /etc/hosts file to push |


## Example Playbook

```yaml
- name: Network Build Hosts
  hosts:
    - cluster_machines
    - standalone_machine
  roles:
    - { role: seapath_ansible.network_buildhosts }
```
