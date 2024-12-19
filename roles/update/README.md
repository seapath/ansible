# SEAPATH Update Role

This role can be used to update a SEAPATH machine.

⚠ For the moment, only Yocto’s version of SEAPATH is supported.

## Requirements

No requirement.

## Role Variables

| Variable                | Required | Type   | Default   | Comments                                         |
|-------------------------|----------|--------|-----------|--------------------------------------------------|
| swu_image               | yes      | String | swu_image | Path of the swupdate file on the Ansible machine |

## Dependencies

No dependency.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.update }
```
