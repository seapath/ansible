# Detect Seapath distribution Role

This role detects the Seapath distribution and set the seapath_distro fact.
seapath_distro can have one of the following value:
- Debian
- CentOS
- Yocto

If the role can't detect one of these distro it fails.

## Requirements

No requirement.

## Role Variables

No variables.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.detect_seapath_distro }
```
