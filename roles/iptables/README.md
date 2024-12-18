# Iptables Role

This role configures load iptables rules.

Rules should be defined in iptables-save/iptables-restore format.

Only IPv4 rules or supported.

## Requirements

No requirement.

## Role Variables

Rules can be defined in a file with `iptables_rules_path` or in an Ansible template with `iptables_rules_template_path`. Do not use both variables at the same time.

| Variable                     | Required | Type   | Comments                                                                                                                        |
|------------------------------|----------|--------|---------------------------------------------------------------------------------------------------------------------------------|
| iptables_rules_path          | no       | String | Path in the Ansible machine to a file containing IPv4 iptables rules in iptables-save/iptables-restore format                   |
| iptables_rules_template_path | no       | String | Path in the Ansible machine to an Ansible template file containing IPv4 iptables rules in iptables-save/iptables-restore format |


## Example Playbook

```yaml
- name: Configure Iptables
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.iptables }
```
