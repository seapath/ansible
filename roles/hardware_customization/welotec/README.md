# Welotec hardware customization role

This role applies specific configuration for Welotec hardware:
* Welotec RSAPCMK2:
  * Creates .link files corresponding to Welotec OUI network interfaces.

## Requirements

No requirement.

## Role Variables
* `network_link.yaml`: a var file containing the mapping of network interfaces.


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
      when: welotec is defined and welotec | bool
```
