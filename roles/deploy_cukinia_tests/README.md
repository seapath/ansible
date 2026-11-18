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
| `deploy_cukinia_tests_extra_expected_groups` | list | `[]` | Additional groups to accept in the expected groups check of `/etc/group` and `/etc/gshadow` (SEAPATH-00033). |

Roles may also publish extra essential services as drop-in files under
`/etc/cukinia/extra-essential-services.d/`. These files are read at
cukinia test runtime, even when tests are deployed or executed later in a
separate playbook run.

Extra expected groups can be published the same way, one group per line,
in drop-in files under `/etc/cukinia/extra-expected-groups.d/`.

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
    deploy_cukinia_tests_extra_expected_groups:
      - my_custom_group
```
