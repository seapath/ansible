# Configure Libvirt Role

This enables and starts the libvirtd service and associated socket.

Also, if `configure_libvirt_allow_non_root_libvirt_socket_access` is set to
true, this role configures the Libvirt socket to be accessible by non-root users
when they are in the libvirt group.
This is useful for the Libvirt administration user to
- Provide live migration over the cluster
- Allow VM console access over the cluster

## Requirements

No requirement.

## Role Variables

| Variable                                               | Required | Type    | Default | Comments                                                                                   |
|--------------------------------------------------------|----------|---------|---------|--------------------------------------------------------------------------------------------|
| configure_libvirt_allow_non_root_libvirt_socket_access | no       | Boolean | true    | Allow non-root users in libvirt group to access libvirt socket                             |
| configure_libvirt_tap_link_speed                       | no       | Integer | 0       | Link speed in Mb/s reported by the guest tap devices, see below. 0 keeps the default       |

## Tap link speed

`configure_libvirt_tap_link_speed` sets the link speed, in Mb/s and full
duplex, that the tap devices of the guests report, for example `1000`
instead of the kernel's 10 Mb/s. It changes what supervision tools (SNMP
`ifSpeed`, node_exporter) read, never the traffic. macvtap, vhost-user and
passthrough interfaces are left alone.

Enabling it for the first time restarts `libvirtd` (`virtqemud` on
OracleLinux): do it before deploying the VMs, or with the cluster in
maintenance mode. VMs already running get the new speed at their next start.

## Example Playbook

```yaml
- hosts: hypervisors
  become: true
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
