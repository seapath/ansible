# Deploy cukinia tests Role
This role deploys the cukinia tests for Debian

## Requirements
No requirement.

## Role Variables
| Variable | Type | Default | Description |
|---|---|---|---|
| `debian_tests_extra_essential_services` | list | `[]` | Additional systemd services to whitelist in the unrecognized services check (SEAPATH-00200). |
| `debian_tests_extra_essential_packages` | list | `[]` | Additional apt packages to whitelist in the unrecognized packages check (SEAPATH-00198). |

## Example Playbook
```yaml
- name: deploy cukinia tests
  hosts:
    - cluster_machines
    - standalone_machine
    - VMs
  become: true
  roles:
    - { role: seapath_ansible.debian_tests, filter: "none" }
  vars:
    debian_tests_extra_essential_services:
      - ha_cluster_exporter
      - my_custom_service
    debian_tests_extra_essential_packages:
      - my_custom_package
\```
```
