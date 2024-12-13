# Network Networkd Wait Role

This role configure the networkd wait service

## Requirements

no requirement.

## Role Variables

- cluster_ip_addr
- cluster_protocol
- interfaces_to_wait_for
- team0_0
- team0_1

## Example Playbook

```yaml
- name: Network Networkd Wait
  hosts:
    - cluster_machines
    - standalone_machine
  roles:
    - { role: seapath_ansible.network_networkdwait }
```
