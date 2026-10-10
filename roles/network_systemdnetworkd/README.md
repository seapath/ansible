# Network systemd-networkd Role

This role configures the network via systemd-networkd

Note: This role is originally copied from https://github.com/aruhier/ansible-role-systemd-networkd and thus under BSD license.

## Requirements

no requirement.

## Role Variables

The network role is separated in three parts :
- A configuration part, that enables specific networks and let the user defined its own
- A cluster network part configures IP address on the cluster.
- An administration part that configures the br0 bridge

### Configuration

| Variable                                   | Required | Type   | Comments                                                                     |
|--------------------------------------------|----------|--------|------------------------------------------------------------------------------|
| network_simple                             | No       | Bool   | Put to true to avoid defining the administration network. See below          |
| network_systemdnetworkd_no_cluster_network | No       | Bool   | Put to true to avoid defining the cluster IP configuration. See below        |
| network_systemdnetworkd_apply_config       | No       | Bool   | Apply the configuration directly, or wait for next reboot to be applied      |
| custom_netdev                              | No       | Custom | Additional systemd-networkd network for the user to define. See syntax below |
| custom_network                             | No       | Custom | Additional systemd-networkd netdev for the user to define. See syntax below  |

The `custom_netdev` and `custom_network` variables are structure uses systemd-networkd files structure in a yaml format.
For example to define a new VLAN:

```yaml
custom_netdev:
  00-vlan100: # Name of the netdev file
    - NetDev:
      - Kind: "vlan" # quotes are mandatory on key-value lines
    - VLAN:
      - Id: "100"

custom_network:
  01-interfaceonvlan100: # Name of the network file
    - Match:
      - Name: "eno1"
    - Network:
      - VLAN: "eno1.100"
```

### Cluster network

| Variable           | Required | Type    | Default | Comments                                                            |
|--------------------|----------|---------|---------|---------------------------------------------------------------------|
| cluster_ip_addr    | Yes      | String  |         | IP address of the machine on the cluster network                    |
| team0subnet        | No       | Integer | 24      | Subnet of the cluster network in CIDR notation                      |
| team0_0            | Yes      | String  |         | Name of the first interface of the machine on the cluster network   |
| team0_1            | Yes      | String  |         | Name of the second  interface of the machine on the cluster network |

### Administration network

The administration part will configure a bridge on the administration interface.
It can be used to connect to the VMs and the hypervisor on the same interface.

| Variable           | Required | Type    | Default | Comments                                                               |
|--------------------|----------|---------|---------|------------------------------------------------------------------------|
| ip_addr            | Yes      | String  |         | Administration IP of the machine. Should be the same as `ansible_host` |
| network_interface  | Yes      | String  |         | Name of the machine interface to put on the administration network     |
| gateway_addr       | Yes      | String  |         | IP address of the gateway on the administration network                |
| subnet             | No       | Integer | 24      | Subnet of the administration network in CIDR notation                  |
| br0vlan            | No       | Integer |         | Number of the VLAN to configure a VLAN on the br0 bridge               |
| network_systemdnetworkd_br0_macvlan | No | Bool | false | Put to true to carry the administration IP on a macvlan of the bridge. See below |

#### Workloads on a macvlan of the bridge

A workload whose interface is a macvlan on `br0` (a container of `deploy_containers_cluster` on the station bus, for example) reaches every machine of that network but the one it runs on: Linux passes no frame between a macvlan and the address of its parent. Such a workload cannot read the metrics proxy of its own hypervisor, nor any other service the hypervisor serves on that address.

With `network_systemdnetworkd_br0_macvlan: true`, the bridge keeps no address. The role creates `macvlan0`, a macvlan of `br0` in bridge mode, and gives it `ip_addr` and `gateway_addr`: the hypervisor and the workloads are then macvlans of the same parent, and talk to each other. With `br0vlan`, `macvlan0` is made on the VLAN interface, which is the one that carried the address.

What it changes on a machine:

- The administration IP answers from the MAC address of `macvlan0`, another one than the bridge's. A switch that filters by MAC address, or a DHCP reservation, has to know it.
- Every macvlan workload of the bridge reaches the services the hypervisor listens to on that address (SSH among them), which the macvlan kept them from until then.
- The guests and the other ports of the bridge are left as they are.

Give the option to all the machines a workload may run on. On a machine already deployed, the change is applied at the next reboot, or at once with `network_systemdnetworkd_apply_config`: the administration IP is then out of reach for the few seconds systemd-networkd takes to move it, and a cluster machine stays reachable meanwhile by its cluster network.

A `custom_network` that matches `br0` and gives it addresses takes precedence over the file of the role, as it always did: move these addresses to a `custom_network` that matches `macvlan0`.

## Example Playbook

```yaml
- name: Network systemd-networkd
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.network_systemdnetworkd }
```
