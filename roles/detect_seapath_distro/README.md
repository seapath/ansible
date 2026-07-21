<!--
Copyright (C) 2024 Savoir-faire Linux, Inc.
Copyright (C) 2026 RTE
SPDX-License-Identifier: Apache-2.0
-->

# Detect Seapath distribution Role

This role detects the Seapath distribution and set the seapath_distro fact.
seapath_distro can have one of the following value:
- Debian
- CentOS
- OracleLinux
- Yocto
- SLES

If the role can't detect one of these distro it fails.

The role also gathers the `ansible_distribution*` facts if they are not already
available.

## Requirements

No requirement.

## Role Variables

| Variable | Description |
| --- | --- |
| `seapath_distro` | Optional. If set, it is used as is and no detection is performed. The value must be one of the distributions listed above. |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.detect_seapath_distro }
```

Forcing the distribution from the inventory, which skips the detection:

```yaml
cluster_machines:
  hosts:
    hypervisor1:
      seapath_distro: Debian
```
