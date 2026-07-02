# Configure NIC IRQ affinity Role

Configure the hosts NICs IRQs affinity
This is useful is you use macvlan driver for your containers or VMs

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type       | Comments                                                           |
|-------------------------|----------|----------- |--------------------------------------------------------------------|
| nics_affinity           | Yes      | Dict array | Array of dictionnaries, nic / affinity (e.g. "eth0": "3-4"). Affinity can be a single core, or a range seperate by *-*. Multiple values can be set separate by a coma. Alternatively `slot=<name>` resolves the CPU through a named seapath-alloc shared-core slot (see below). |

## seapath-alloc integration

When the `deploy_seapath_alloc` role is also deployed on the host, an
interface's affinity can be set to `slot=<name>` instead of a static CPU
list. The monitor daemon (`nic-irq-monitor.sh`) then calls
`seapath-alloc slot <name>` to resolve the CPU: the slot is
allocated from the isolated-core pool on first use and returned as-is on
every subsequent call, so the IRQs land back on the same core after a link
bounce, and other actors (VM thread groups, containers, `seapath-run`
processes) referencing the same slot name share that core with the IRQs.

`slot=` requires `seapath-alloc` on the host: if the binary is missing or
the pool is exhausted, the interface's IRQs are left unpinned and a message
is logged.

## Example Playbook

```yaml
- hosts: cluster_machines
  vars:
    nics_affinity:
      - "eth0": "3-4"
      - "eth1": "9"
      - "eth2": "7,10-13"
      - "eth3": "slot=sv0"   # share a seapath-alloc slot with other actors
  roles:
    - { role: seapath_ansible.configure_nic_irq_affinity }
```
