# Deploy python3-setup-ovs Role

deploys python3-setup-ovs (seapath-config_ovs)

## Requirements

No requirement.

## Role Variables

No variable.

## Example Playbook

```yaml
- name: Deploy python3-setup-ovs
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.python3-setup-ovs }
```
