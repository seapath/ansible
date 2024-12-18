# Add LiveMigration User Role

This role sets the live migration user on the cluster, with ssh key exchanges.
If the user does not already exist, they will be created.

## Requirements

no requirement.

## Role Variables

| Variable                | Required | Type   | Comments                                                           |
|-------------------------|----------|--------|--------------------------------------------------------------------|
| livemigration_user      | no       | String | The livemigration user. If not defined, the role will do nothing.  |


## Example Playbook

```yaml
- name: Create livemigration user
  hosts: hypervisors
  gather_facts: true
  become: true
  roles:
    - { role: seapath_ansible.add_livemigration_user }
```
