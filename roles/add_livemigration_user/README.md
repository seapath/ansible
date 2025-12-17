# Add LiveMigration User Role

This role sets the live migration user on the cluster, with ssh key exchanges.
If the user does not already exist, it will be created.

## Requirements

no requirement.

## Role Variables

| Variable                | Required | Type   | Comments               |
|-------------------------|----------|--------|------------------------|
| livemigration_user      | yes      | String | The livemigration user |


## Example Playbook

```yaml
- name: Create livemigration user
  hosts: hypervisors
  gather_facts: true
  become: true
  roles:
    - { role: seapath_ansible.add_livemigration_user }
```
