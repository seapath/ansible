# Deploy cukinia tests Role
This role deploys SEAPATH cukinia tests.
Note that this role doesn't handle cukinia tests for SEAPATH Yocto.

## Requirements
No requirement.

## Role Variables
| Variable | Type | Default | Description |
|---|---|---|---|
| `deploy_cukinia_tests_extra_essential_services` | list | `[]` | Additional systemd services to whitelist in the unrecognized services check (SEAPATH-00200). |
| `deploy_cukinia_tests_extra_essential_packages` | list | `[]` | Additional apt packages to whitelist in the unrecognized packages check (SEAPATH-00198). |

## Example Playbook
```yaml
- name: deploy cukinia tests
  hosts:
    - cluster_machines
    - standalone_machine
    - VMs
  become: true
  roles:
    - { role: seapath_ansible.deploy_cukinia_tests, filter: "none" }
  vars:
    deploy_cukinia_tests_extra_essential_services:
      - ha_cluster_exporter
      - my_custom_service
    deploy_cukinia_tests_extra_essential_packages:
      - my_custom_package
```
