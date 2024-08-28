# Iptables Role

This role configures iptables

## Requirements

no requirement.

## Role Variables

- iptables_rules_path
- iptables_rules_template_path

## Example Playbook

```yaml
- name: Configure Iptables
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.iptables }
```
