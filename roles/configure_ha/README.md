# Configure HA Role

This role configures the High Availability part of a seapath cluster (Corosync and Pacemaker)

## Requirements

No requirement.

## Role Variables

| Variable                             | Required | Type        | Default | Comments                                                                       |
|--------------------------------------|----------|-------------|---------|--------------------------------------------------------------------------------|
| seapath_distro                       | yes      | String      |         | SEAPATH variant. *CentOS*, *Debian* or *Yocto*. The variable can be set automatically using the *detect_seapath_distro role* |
| corosync_node_list                   | yes      | String list |         | List of all corosync nodes. Usually `{{ groups['cluster_machines'] \| list }}` |
| configure_ha_tmpdir                  | no       | String      | /tmp    | Temporary directory path to use                                                |
| enable_vmmgr_http_api   | no       | Bool        | false   | Set to true to enable SEAPATH vm-manager REST API                              |
| admin_cluster_ip                     | no       | String      |         | IP of the REST API. If not set the m-manager REST API will be disabled even if `enable_vmmgr_http_api is set to true` |
| extra_crm_cmd_to_run                 | no       | String      |         | List of `crm configure` commands to run separate by a new line.                |

## Example Playbook

```yaml
- name: Configure HA
  hosts: cluster_machines
  vars:
    corosync_node_list: "{{ groups['cluster_machines'] | list }}"
    extra_crm_cmd_to_run: >-
      primitive st-1 stonith:external/rackpdu params hostlist=h1 pduip=192.168.3.127
      location l-st-h1 st-1 -inf: h1
      primitive st-2 stonith:eexternal/rackpdu params hostlist=h2 pduip=192.168.3.128
      location l-st-h2 st-2 -inf: h2
      primitive st-3 stonith:eexternal/rackpdu params hostlist=h3 pduip=192.168.3.129
      location l-st-h3 st-3 -inf: h3
      property stonith-enabled=true

  roles:
    - { role: seapath_ansible.configure_ha }
```
