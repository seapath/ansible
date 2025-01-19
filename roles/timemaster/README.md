# Timemaster Role

This role configures timemaster

## Requirements

No requirement.

## Role Variables

| Variable                         | Required | Type    | Default | Comments                                                                                                                               |
|----------------------------------|----------|---------|---------|----------------------------------------------------------------------------------------------------------------------------------------|
| seapath_distro                   | yes      | String  |         | SEAPATH variant. CentOS, Debian or Yocto. The variable can be set automatically using the detect_seapath_distro role                   |
| ptp_interface                    | no       | String  |         | Network interface to use for PTP. The interface must support PTP hardware reception. If not set the PTP configuration will be skipped. |
| ptp_vlanid                       | no       | Integer |         | Optional VLAN ID to use with PTP                                                                                                       |
| ntp_servers                      | no       | String  |         | List of NTP/SNTP servers separated by a new line. If not set NTP configuration will be skipped                                         |
| timemaster_ptp_network_transport | no       | String  | "L2"    | PTP transport configuration. "L2" or "UDP"                                                                                             |
| timemaster_ptp_delay_mechanism   | no       | String  | "P2P"   | PTP delay mechanism. "P2P" or "E2E"                                                                                                    |


## Example Playbook

```yaml
- name: Configure Timemaster
  hosts: cluster_machines
  become: true
  vars:
    ptp_interface: "ens0"
    ptp_vlanid: 100
    ntp_servers: >-
      192.168.1.4
      192.168.1.8
  roles:
    - { role: seapath_ansible.timemaster }
```
