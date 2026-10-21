# Configure NIC IRQ affinity Role

Configure the hosts NICs IRQs affinity
This is useful is you use macvlan driver for your containers or VMs

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type       | Comments                                                           |
|-------------------------|----------|----------- |--------------------------------------------------------------------|
| nics_affinity           | Yes      | Dict array | Array of dictionnaries, nic / affinity (e.g. "eth0": "3-4"). Affinity can be a single core, or a range seperate by *-*. Multiple values can be set separate by a coma. Alternatively `slot=<name>:<cpu>` pins to `<cpu>` and declares a named seapath-alloc shared-core slot on it (see below). |

| nics_rx_usecs           | No       | Dict array | Array of dictionnaries, nic / receive interrupt coalescing in microseconds, as `ethtool -C <nic> rx-usecs` takes it (e.g. "eth0": 0). Needs `ethtool` on the host. |

Either variable may be given alone.

## Receive interrupt coalescing

A NIC's driver may hold a received frame back to take fewer interrupts. igb's
default, `rx-usecs 3`, is its "dynamic conservative" mode: under light traffic
an interface takes one interrupt every 50 us or so. Sampled Values come in
bursts, the streams of every merging unit synchronised on the same instant,
and every frame of a burst after the first waits for the next interrupt.
On a SEAPATH node receiving ten streams at 4800 samples a second, with
`rx-usecs 0` (an interrupt for every frame):

| | `rx-usecs 3` | `rx-usecs 0` |
|---|---|---|
| sample instant to a protection's decision, second stream of the burst | 125 us | 61 us |
| the same, last stream | 167 us | 124 us |
| the NIC's interrupts | 7,100/s | 11,600/s |
| the IRQ thread's core, busy | 17.4 % | 18.6 % |

The monitor sets the value at its start and each time the interface comes up,
as it does the affinity: a driver reload puts the default back.

## seapath-alloc integration

When the `seapath_alloc` role is also deployed on the host, an
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
    nics_rx_usecs:
      - "eth3": 0               # an interrupt for every frame of the process bus
  roles:
    - { role: seapath_ansible.configure_nic_irq_affinity }
```
