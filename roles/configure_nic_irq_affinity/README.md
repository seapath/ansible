# Configure NIC IRQ affinity Role

Configure the hosts NICs IRQs affinity
This is useful is you use macvlan driver for your containers or VMs

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type       | Comments                                                           |
|-------------------------|----------|----------- |--------------------------------------------------------------------|
| nics_affinity           | Yes      | Dict array | Array of dictionnaries, nic / affinity (e.g. "eth0": "3-4"). Affinity can be a single core, or a range seperate by *-*. Multiple values can be set separate by a coma. Alternatively `slot=<name>:<cpu>` pins to `<cpu>` and declares a named seapath-alloc shared-core slot on it (see below). |

## seapath-alloc integration

When the `deploy_seapath_alloc` role is also deployed on the host, an
interface's affinity can be written `slot=<name>:<cpu>`: the CPU comes from
the inventory and is pinned unconditionally, like a static value, but the
monitor additionally declares a named shared-core slot on that core to
seapath-alloc. Other actors (VM thread groups, containers, `seapath-run`
processes) referencing the slot name then share the core with the IRQs.
Pinning never depends on seapath-alloc — if it is missing, only the
colocation opportunity is lost.

## Example Playbook

```yaml
- hosts: cluster_machines
  vars:
    nics_affinity:
      - "eth0": "3-4"
      - "eth1": "9"
      - "eth2": "7,10-13"
      - "eth3": "slot=sv0:14"   # pin to cpu 14 and declare slot sv0 on it
  roles:
    - { role: seapath_ansible.configure_nic_irq_affinity }
```
