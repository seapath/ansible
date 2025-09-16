# network configovs Role

SEAPATH uses OVS (Open vSwitch) to connect physical network interface and VMs
together and manage VLANs.

OVS also leverages DPDK-enabled NICs to provide a high performance (in both
throughput and latency) layer 2 network.

This role configures additional Open vSwitch bridges

## Requirements

No requirement.

## Role Variables

| Variable                       | Required | Type        | Defaults  | Comments                                                                                                     |
|--------------------------------|----------|-------------|---------- |--------------------------------------------------------------------------------------------------------------|
| ovs_bridges                    | No       | Dict List   |           | List of Open vSwitch bridges. Structure is described below                                                   |
| ignored_bridges                | No       | String list | ["team0"] | List of OVS bridges to be ignored by this role. If present on your setup, team0 must always be ignored       |
| ignored_taps                   | No       | String list |           | List of tap interface to be ignored by this role                                                             |
| unbind_pci_address             | No       | String list |           | List of PCI addresses to "unbind".                                                                           |
| ovs_vsctl_cmds                 | No       | String list |           | List of additional Open vSwtich commands to run with ovs-vsctl                                               |
| interfaces_on_br0              | No       | Dict List   |           | List of br0 tap interfaces defined for the `network_guestinterfaces` role. They will be ignored by this role |
| seapath_distro                 | Yes      | String      |           | SEAPATH variant. CentOS, Debian or Yocto. It is set by the role `detect_seapath_distro`                      |
| network_configovs_apply_config | Yes      | Bool        | false     | Apply the OVS configuration immediately. Otherwise, it will be applied at the next reboot                    |

## Example Playbook

```yaml
- name: Configure OVS
  hosts: cluster_machines
  become: true
  roles:
    - { role: seapath_ansible.network_configovs }
```

## Declare an OVS bridge in the Ansible inventory

In SEAPATH, only hypervisors can set-up OVS bridges. All OVS bridges with its
corresponding port configuration must be statically described in the Ansible
inventory.

To achieve this, the variable _ovs_bridges_ must be defined. The OVS
configuration can be the same for all the hypervisors if this variable is
defined as a global variable or hypervisors group variable. Or it can be
specific to a hypervisor that variable is declared at the hypervisor level.

The variable must comply with the following YAML schema:

```yaml
ovs_bridges:
  - name: string
    rstp_enable: bool
    enable_ipv6: bool
    other_config: string | [ string ]
    ovsvsctl_extra_cmds:
      - "set Bridge brTEST netflow=@nf0 -- --id=@nf0 create NetFlow targets=\"192.168.56.201:2055\" add_id_to_interface=true"
      - "-- --id=@sflow create sflow agent=br0 target=\"192.168.56.201:6343\" header=128 sampling=64 polling=10 -- set bridge brTEST sflow=@sflow"
    flows_override: |
      table=0,priority=1,action=drop
      table=0,priority=10,arp,action=normal
      table=0,priority=100,ip,ct_state=-trk,action=ct(table=1)
      table=1,nw_src=10.0.0.1,nw_dst=10.0.0.2,ip,icmp,ct_state=+trk+new,action=ct(commit),normal
    ports:
      - name: string
        type: internal | system | dpdk | dpdkvhostuserclient | tap | vxlan
        tag: integer
        trunks: integer | [ integer ]
        vlan_mode: access | native-tagged | native-untagged | trunk
        mac: string
        ip: string | [ string ]
        interface: string
        ofport_request: integer
        other_config: string | [ string ]
        remote_ip: string
        remote_port: interger
        key: string
        ingress_policing_rate: interger
        ingress_policing_burst: interger
```

The ovs_bridges takes a bridge list with the following mandatory attributes:

- *name*: the interface bridge name
- *rstp_enable*: set to true to enable RSTP on the bridge. Default is false.
- *enable_ipv6*: if false all ipv6 paquet will be dropped. Default is false. Ignored when flows_override is defined.
- *flows_override*: if defined, then the list of flows will override the normal openflow created based on enable_ipv6 and mac/ip variables
- *ofport_request*: if defined, create the port with the ofport_request option set (request a specific openflow port number)
- *other_config*: optional OVS configuration for the bridge as you can pass with `other_config=` when running the command `ovs-vsctl`.
- *ovsvsctl_extra_cmds*: if defined, the setup_ovs tool will run these commands after creating the bridge
- *ports*: the list of OVS ports in the bridge

Each port has the following attributes:

- *name*: the port interface name. Mandatory.
- *type*: The port type. Mandatory. The port must be one of the following types:
    - *system*:
       A port attached to a system interface. The interface to attach to must be set
       in the _interface_ variable. +
       This type of port cannot be attached to a VM.
    - *dpdk*:
       Same as system but for DPDK managed interface. The PCI NIC address must be
       set in the _interface_ variable. +
       This type of port cannot be attached to a VM.
    - *internal*:
       Port which is not attached to any interface and is only virtual. +
       This port is for the host. +
       This type of port cannot attached to a VM.
    - *tap*:
       If it does not already exists create a tap device and attach it to the
       bridge. +
       This type of port can be attached to a VM.
    - *dpdkvhostuserclient*:
       Same as internal but create a port that use DPDK. +
       This type of port can be attached to a VM.
    - *vxlan*:
       Create a vxlan interface and attached it to the port. +
       Use remote_ip, remote_port and key to configure it
- *interface*: The interface to attach to the port. NIC for DPDK or Linux
               interface for system, not used for other port types
- *tag*: optional integer, in range 0 to 4,095 +
         For an access port, the port’s implicitly tagged VLAN. +
         For a native-tagged or native-untagged port, the port’s native VLAN. +
         Must be empty if this is a trunk port.
- *trunk*: list of up to 4,096 integers, in range 0 to 4,095 +
            For a trunk, native-tagged, or native-untagged port, the 802.1Q VLAN
            or VLANs that this port trunks; if it is empty, then the port trunks
            all VLANs. +
            Must be empty if this is an access port. +
            A native-tagged or native-untagged port always trunks its native
            VLAN, regardless of whether trunks include that VLAN.
- *vlan_mode*: Bridge ports support the following types of VLAN configuration:
    - *trunk*:
        A trunk port carries packets on one or more specified VLANs specified in the
        trunks column (often, on every VLAN). A packet that ingresses on a trunk
        port is in the VLAN specified in its 802.1Q header, or VLAN 0 if the packet
        has no 802.1Q header. A packet that egresses through a trunk port will have
        an 802.1Q header if it has a nonzero VLAN ID. +
        Any packet that ingresses on a trunk port tagged with a VLAN that the port
        does not trunk is dropped.
    - *access*:
        An access port carries packets on exactly one VLAN specified in the tag
        column. Packets egressing on an access port have no 802.1Q header. +
        Any packet with an 802.1Q header with a nonzero VLAN ID that ingresses on an
        access port is dropped, regardless of whether the VLAN ID in the header is
        the access port’s VLAN ID.
    - *native-tagged*:
        A native-tagged port resembles a trunk port, with the exception that a
        packet without an 802.1Q header that ingresses on a native-tagged port is in
        the _native VLAN_ (specified in the tag column).
    - *native-untagged*:
        A native-untagged port is like a native-tagged port, with the exception
        that a packet that egresses on a native-untagged port in the native VLAN
        will not have an 802.1Q header.
- *mac*:
  Ingresses source MAC address accepted. All others sources will be dropped. +
  Only works with tap or dpdkvhostuserclient. Ignored when flows_override is defined.
- *ip*:
  Ingresses source IP addresses accepted list. All others sources will be
  dropped. +
  Only works with tap or dpdkvhostuserclient. Ignored when flows_override is defined.
- *remote_ip*:
  vxlan remote IP to connect.
- *remote_port*:
  vxlan remote port. Default is 4789.
- *key*:
  vxlan key.
- *other_config*:
  Optional additional OVS port configurations as you can pass with
  _other_config=_ when running `ovs-vsctl`.
- *ingress_policing_rate*:
  The maximum rate (in Kbps) that this port should be allowed to send. +
  If not set, this policy will be disabled.
- *ingress_policing_burst*:
  A parameter to the policing algorithm to indicate the maximum amount of data
  (in Kb) that this interface can send beyond the policing rate. +
  If not set, this policy will be disabled.

## OVS configuration example

```yaml
all:
  children:
    cluster_machines:
      children:
        hypervisors:
          vars:
            ovs_bridges:
              - name: ovsbr0
                ports:
                  - name: ovsbr0VirtualPort0
                    type: tap
                    tag: 40
                    ingress_policing_rate: 1000
                    ingress_policing_burst: 500
                    vlan_mode: native-untagged
                    mac: "77:fd:4d:68:30:3b"
                    ip: "192.168.4.3"
                  - name: ovsbr0VirtualPort1
                    type: tap
                    tag: 40
                    vlan_mode: native-untagged
                    mac: "77:fd:4d:68:30:3c"
                    ip: "192.168.4.3"
                  - name: ovsbr0HostPort
                    type: internal
                    tag: 40
                    vlan_mode: native-untagged
                  - name: ovsbr0ExternalPort
                    type: system
                    interface: eno1
              - name: dpdkbr0
                ports:
                  - name: dpdkbr0VirtualPort0
                    type: dpdkvhostuserclient
                    trunks:
                      - 300
                      - 2170
                      - 1170
                    mac: "94:9b:37:7b:87:50"
                    ip:
                        - "10.10.1.7"
                        - "192.168.27"
                        - "10.4.1.7"
                  - name: dpdkbr0VirtualPort1
                    type: dpdkvhostuserclient
                    tag: 300
                    vlan_mode: native-untagged
                    mac: "94:9b:37:7b:87:51"
                    ip: "10.10.1.8"
                  - name: dpdkbr1ExternalPort
                    type: dpdk
                    interface: "0000:08:00.1"
```

## Host port network configuration

It is possible to configure an internal port not used by the VM to access to the
bridge network from the host. This can be done as another network interface
using the custom_network variable. This situation is illustrated in the example below.

```yaml
all:
  children:
    cluster_machines:
      children:
        hypervisors:
          vars:
            00-ovsbr0ExternalPort:
                - Match:
            - Name: "ovsbr0ExternalPort"
            - Network:
                - Address: "192.168.54.5/24"
```
