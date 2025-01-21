# Cluster Network Role

This role configures the cluster network.

## Requirements

No requirement.

## Role Variables

| Variable                   | Required  | Type        | Comments                                                         |
|----------------------------|-----------|-------------|------------------------------------------------------------------|
| team0_0                    | Yes       | String      | First network interface use for the ring cluster                 |
| team0_1                    | Yes       | String      | Second network interface use for the ring cluster                |
| br_rstp_priority           | no        | Integer     | RSTP priority. Default 16384                                     |
| conntrackd_ignore_ip_list  | No        | List        | If defined, conntrackd service will be restarted                 |
| cluster_protocol           | No        | RSTP or HSR | Protocol for the ring cluster network. Default is RSTP           |
| hsr_mac_address            | No        | String      | MAC address of the HSR interface                                 |
| skip_recreate_team0_config | No        | bool        | Set to false to force recreate the team0 bridge. Default is true |


## Example Playbook

```yaml
- name: Configure Cluster Network
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.network_clusternetwork }
```
