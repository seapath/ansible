# Add LiveMigration User Role

This role sets the live migration user on the cluster, with ssh key exchanges

## Requirements

no requirement.

## Role Variables

- livemigration_user

## Example Playbook

```yaml
- name: Create livemigration user
  hosts: hypervisors
  gather_facts: true
  become: true
  roles:
    - { role: seapath_ansible.add_livemigration_user }
```
