# Network Guests br0 interfaces Role

This role creates the interfaces for guests which need to be on br0.

## Requirements

No requirement.

## Role Variables

| Variable              | Required  | Type          | Comments                                           |
|-----------------------|-----------|---------------|----------------------------------------------------|
| interfaces_on_br0     | No        | List of dict  | Tap interface to create on br0 with specific vlans |

The interfaces_on_br0 variable is a list of dictionnaries defining a name for the tap interface and the associated vlans.

```yaml
interfaces_on_br0:
  INTERFACE1: 159       #access port on vlan 159
  INTERFACE2: [159,160] #trunk port on vlan 159 and 160
  INTERFACE3: [1-4094]  # no filtering, excluding untagged trafic
  INTERFACE4: []        # no filtering, including untagged trafic
```

## Example Playbook

```yaml
- name: Network Guests BR0 interfaces
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_guestsinterfaces }
```
