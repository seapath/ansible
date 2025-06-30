# CI Re-install ISO

This role reinstalls the VM with the seapath debian iso

## Requirements

- detect_seapath_distro

## Role Variables


## Example Playbook

```yaml
- name: CI reinstall iso
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.ci_reinstalliso }
```
