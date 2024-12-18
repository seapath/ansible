# Configure NIC IRQ affinity Role

Configure the hosts NICs IRQs affinity
This is useful is you use macvlan driver for your containers or VMs

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type       | Comments                                                           |
|-------------------------|----------|----------- |--------------------------------------------------------------------|
| nics_affinity           | no       | Dict array | Array of dictionnaries, nic / affinity (e.g. "eth0": "3-4"). Affinity can be a single core, or a range seperate by *-*. Multiple values can be set separate by a coma. |

## Example Playbook

```yaml
- hosts: cluster_machines
  vars:
    nics_affinity:
      - "eth0": "3-4"
      - "eth1": "9"
      - "eth2": "7,10-13"
  roles:
    - { role: seapath_ansible.configure_nic_irq_affinity }
```
