# Welotec hardware customization role

This role applies specific configuration for Welotec hardware:
* Welotec RSAPCMK2:
  * Creates .link files corresponding to Welotec OUI network interfaces.

## Requirements

No requirement.

## Role Variables
* `network_link.yaml`: a var file containing the mapping of network interfaces.
* `welotec_rsapcmk2`: a boolean variable to enable or disable the role.
  Default is `false`.

## Example Playbook

```yaml
- name: Welotec hardware customization
  hosts:
    - cluster_machines
    - standalone_machine
  become: true
  gather_facts: true
  roles:
    - role: hardware_customization/welotec
      when: welotec_rsapcmk2 is defined and welotec_rsapcmk2 | bool
```
