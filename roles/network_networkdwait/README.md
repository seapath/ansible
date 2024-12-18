# Network Networkd Wait Role

This role configure the networkd wait service.

## Requirements

No requirement.

## Role Variables

| Variable               | Requiered | Type           | Comments                                               |
|------------------------|-----------|----------------|--------------------------------------------------------|
| cluster_protocol       | No        | RSTP or HSR    | Protocol for the ring cluster network. Default is RSTP |
| cluster_ip_addr        | No        | String         | Cluster network interface IP address                   |
| interfaces_to_wait_for | No        | List of string | Interface not mandatory to be setup at boot time       |


## Example Playbook

```yaml
- name: Network Networkd Wait
  hosts:
    - cluster_machines
    - standalone_machine
  roles:
    - { role: seapath_ansible.network_networkdwait }
```
