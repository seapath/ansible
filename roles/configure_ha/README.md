# Configure HA Role

This role configures the High Availability part of a seapath cluster (Corosync and Pacemaker)

## Requirements

no requirement.

## Role Variables

- corosync_node_list
- tmpdir
- crm_cmd_path
- vmmgrapi_cmd_list
- extra_crm_cmd_to_run

## Example Playbook

```yaml
- name: Configure HA
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_ha }
```
