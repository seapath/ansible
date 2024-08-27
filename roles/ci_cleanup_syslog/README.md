# Cleanup Syslog-ng Role

This role removes the content of the /var/log/syslog-ng folder

## Requirements

no requirement.

## Role Variables

no variable.

## Example Playbook

```yaml
- name: Cleanup syslog-ng files
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.ci_cleanup_syslog }
```
