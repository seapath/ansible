# Configure NIC IRQ affinity Role

Configure the hosts NICs IRQs affinity
This is useful is you use macvlan driver for your containers or VMs

## Requirements

no requirement.

## Role Variables

- nics_affinity

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_nic_irq_affinity }
```
