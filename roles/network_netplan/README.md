# Network Netplan Role

This role configures the network via Netplan.

## Requirements

No requirement.

## Role Variables

| Variable               | Required  | Type           | Comments                                                                               |
|------------------------|-----------|----------------|----------------------------------------------------------------------------------------|
| netplan_configurations | No        | List of string | List of netplan Ansible template files on the Ansible machine to be uploaded on target |
| ptp_interface          | No        | String         | PTP interface name.                                                                    |
| ptp_vlanid             | No        | Integer        | VLAN ID for PTP. If defined and non-empty, the role auto-generates `/etc/netplan/99-ptp-vlan.yaml`. |

When both `ptp_interface` and `ptp_vlanid` are defined and non-empty, the role creates a supplemental netplan file (`99-ptp-vlan.yaml`) to bring up the VLAN interface. If you prefer to define the VLAN manually in your own netplan template, leave `ptp_vlanid` undefined.

## Example Playbook

```yaml
- name: Network Netplan
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_netplan }
```
