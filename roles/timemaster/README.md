# Timemaster Role

This role configures timemaster

## Requirements

No requirement.

## Role Variables

| Variable                         | Required | Type    | Default | Comments                                                                                                                               |
|----------------------------------|----------|---------|---------|----------------------------------------------------------------------------------------------------------------------------------------|
| seapath_distro                   | yes      | String  |         | SEAPATH variant. CentOS, Debian or Yocto. The variable can be set automatically using the detect_seapath_distro role                   |
| ptp_interface                    | no       | String  |         | Network interface to use for PTP. The interface must support PTP hardware reception. If not set the PTP configuration will be skipped. |
| ptp_vlanid                       | no       | Integer |         | Optional VLAN ID to use with PTP                                                                                                       |
| ntp_servers                      | no       | String  |         | List of NTP/SNTP servers separated by a new line. If not set NTP configuration will be skipped                                         |
| timemaster_ptp_network_transport | no       | String  | "L2"    | PTP transport configuration. "L2" or "UDP"                                                                                             |
| timemaster_ptp_delay_mechanism   | no       | String  | "P2P"   | PTP delay mechanism. "P2P" or "E2E"                                                                                                    |
| timemaster_ptp_domain_number     | no       | Integer | 0       | PTP domain number. Value from 0 to 255                                                                                                      |
| timemaster_ptp_minor_version     | no       | Integer | 1       | PTP minor version. 0 or 1                                                                                                        |
| timemaster_ptp_ntp_options       | no       | String  | "trust prefer" with one NTP server or none, "prefer" with two or more | chrony options of the PTP source. trust keeps PTP as the reference when an NTP server disagrees with it, which is needed with a single NTP server but prevents two NTP servers from outvoting a grand master that sends a wrong time. Set to "" to drop them |
| timemaster_ptp_custom_options    | no       | String  | null    | List of options to add to the ptp4l configuration section separated by a new line. Skipped if not set                                                                                                      |


## PTP VLAN on an interface that is also an OVS port

A common SEAPATH layout puts the process bus NIC (`ptp_interface`) in an OVS
bridge for the guest traffic, and declares the PTP VLAN (`ptp_vlanid`) on the
same NIC as a kernel VLAN device created by systemd-networkd (for example
`enp2s0.800`). ptp4l then runs on that VLAN device. This layout is supported
and keeps hardware timestamping. Its side effects are listed below.

### Ingress of the PTP VLAN bypasses OVS

In `__netif_receive_skb_core`, a tagged frame that matches an existing VLAN
device is handed to that device by `vlan_do_receive()` before the
`rx_handler` that OVS registers on the NIC. As a result:

- frames of the PTP VLAN reach ptp4l and never reach OVS. All the other VLANs
  reach OVS normally;
- egress is unaffected: ptp4l and OVS both transmit directly on the NIC.

On a running node, `ovs-appctl fdb/show <bridge>` lists no MAC learned on the
PTP VLAN, which confirms the behaviour.

Consequence: a guest connected to the PTP VLAN through OVS can transmit on it
but receives nothing, without any error. Never put guest traffic (a ptp4l in a
VM, Sampled Values, GOOSE) on the PTP VLAN. Guests get the time from the host
(ptp_kvm / PHC), so they do not need it.

### Hardware VLAN filtering depends on the driver

Creating the VLAN device adds its VID to the NIC hardware VLAN filter
(`rx-vlan-filter`). OVS puts the NIC in promiscuous mode, and most drivers
then accept every VLAN (igb does). Some drivers keep the filter active in
promiscuous mode, especially with SR-IOV VFs enabled (ixgbe, i40e): OVS then
only receives the VLANs declared as kernel devices. Check that the guest VLANs
are learned in the OVS FDB on such NICs, and use
`ethtool -K <interface> rx-vlan-filter off` if they are not.

### Two managers for the same link

systemd-networkd manages the NIC (only to declare the VLAN) and OVS has it as a
port. Keep the networkd `.network` file of the NIC minimal (`[Match]` and
`VLAN=`): any setting that makes networkd bounce the link or change its MTU
drops PTP and the guest traffic at the same time.

### Shared timestamping and TX queues

- The hardware timestamping configuration (`SIOCSHWTSTAMP`) is global to the
  NIC: the VLAN device forwards it to the physical device. Another tool that
  reconfigures timestamping on the NIC overrides the one of ptp4l. OVS does
  not.
- PTP messages share the NIC TX queues with the guest traffic. Hardware
  timestamps keep the precision, but heavy load can delay the TX timestamp
  report (`timed out while polling for tx timestamp`). Raise
  `tx_timestamp_timeout` through `timemaster_ptp_custom_options` if it
  happens.

### Alternatives

- An OVS internal port tagged with the PTP VLAN keeps everything in OVS, but
  an internal port has no PHC: hardware timestamping is lost, which rules it
  out.
- A dedicated NIC for PTP, or an SR-IOV VF on the PTP VLAN when the NIC can
  timestamp on its VFs, avoid all of the above at the cost of hardware or of a
  NIC dependency.

## Example Playbook

```yaml
- name: Configure Timemaster
  hosts: cluster_machines
  become: true
  vars:
    ptp_interface: "ens0"
    ptp_vlanid: 100
    ntp_servers: >-
      192.168.1.4
      192.168.1.8
  roles:
    - { role: seapath_ansible.timemaster }
```
