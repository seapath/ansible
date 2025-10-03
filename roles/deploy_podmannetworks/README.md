# deploy_podmannetworks Role

This role deploys the podman networks according to the inventory

## Requirements

This role requires the containers.podman collection

## Role Variables

Variable                  | Required | Type     | Default  | Comments
--------------------------|----------|---------|---------|---------------------------------------------------------------------------------
podman_networks           | Yes      | list     | []       | Array of Podman networks to create. Each item is a dictionary with network parameters.
podman_networks[].name    | Yes      | string   | -        | Name of the Podman network.
podman_networks[].driver  | Yes      | string   | macvlan  | Network driver to use (e.g., macvlan, bridge).
podman_networks[].subnet  | Yes      | string   | -        | Subnet in CIDR notation (e.g., 10.132.159.0/24).
podman_networks[].gateway | Yes      | string   | -        | Gateway IP for the network.
podman_networks[].parent  | Yes      | string   | -        | Parent interface for macvlan networks (e.g., br0).
podman_networks[].options | No       | dict     | {}       | Additional Podman network options (key: value) passed via -o. Optional.
podman_networks[].state   | No       | string   | present  | Desired state of the network (present or absent).


## Example Playbook

```
- hosts: cluster_machines
  vars:
    podman_networks:
      - name: ceph-macvlan
        driver: macvlan
        subnet: 10.10.159.0/24
        gateway: 10.10.159.1
        parent: br0
  become: true
  roles:
    - deploy_podmannetworks
```
