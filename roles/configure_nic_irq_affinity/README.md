# Configure NIC IRQ affinity Role

Configure the hosts NICs IRQs affinity
This is useful is you use macvlan driver for your containers or VMs

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type       | Comments                                                           |
|-------------------------|----------|----------- |--------------------------------------------------------------------|
| nics_affinity           | Yes      | Dict array | Array of dictionnaries, nic / affinity (e.g. "eth0": "3-4"). Affinity can be a single core, or a range seperate by *-*. Multiple values can be set separate by a coma. |

## seapath-alloc integration

When the `deploy_seapath_alloc` role is also deployed on the host, the monitor
daemon (`nic-irq-monitor.sh`) will call `seapath-alloc suggest` to obtain free
isolated cores dynamically instead of using the static CPU list from
`/etc/nic-irq-affinity.conf`.

The static list in `nics_affinity` is still required as a fallback for hosts
without `seapath-alloc`, or for NIC interfaces that come up before
`seapath-alloc` is ready.

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
