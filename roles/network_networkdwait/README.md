# Network Networkd Wait Role

This role configure the networkd wait service.

## Requirements

No requirement.

## Role Variables

| Variable                                | Required  | Type           | Default | Comments                                         |
|-----------------------------------------|-----------|----------------|---------|--------------------------------------------------|
| cluster_protocol                        | No        | RSTP or HSR    | RSTP    | Protocol for the ring cluster network            |
| interfaces_to_wait_for                  | No        | List of string | Emtpy   | Interface not mandatory to be setup at boot time |
| network_networkdwait_no_cluster_network | No        | Bool           | false   | Wait for the cluster "team0" bridge              |


## Example Playbook

```yaml
- name: Network Networkd Wait
  hosts:
    - cluster_machines
    - standalone_machine
  roles:
    - { role: seapath_ansible.network_networkdwait }
```
