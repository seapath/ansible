# Configure Libvirt Role

This enables and starts the libvirtd service and associated socket.

The role always generates `/etc/libvirt/libvirtd.conf` with the TLS and TCP
listeners disabled and `host_uuid_source = "machine-id"`.

## Non-root socket access

The read/write libvirt socket is **root-equivalent**: whoever can reach it can
start, stop, reconfigure or open the console of every VM, attach host devices
and reach host files through the VM definitions. The role therefore restricts
it, and only opens it to non-root users when
`configure_libvirt_allow_non_root_libvirt_socket_access` is true.

That variable defaults to true when `livemigration_user` is defined and is not
`root` (see [Live migration and console access](#live-migration-and-console-access)),
and to false otherwise.

### Restricted access (non-root access disabled)

Only root, and the trusted system user set by
`configure_libvirt_socket_trusted_user`, can reach libvirt. That user defaults
to `libvirtdbus`, the account libvirt-dbus runs as: cockpit-machines goes
through libvirt-dbus, so its Virtual Machines page stays usable. It is ignored
on hosts where the user does not exist, and `""` disables it.

The role enforces this on these layers:

- `libvirtd.conf`: `unix_sock_*` permissions. Only a libvirtd that is not
  socket-activated reads these settings.
- systemd drop-ins on every libvirt socket unit listed in
  `configure_libvirt_socket_units` (`libvirtd*.socket` on Debian and SLES, the
  modular `virt*d*.socket` daemons on OracleLinux). This is what restricts the
  sockets on socket-activated hosts, where the distribution ships them as
  `0666`.
- a polkit rule, `/etc/polkit-1/rules.d/10-seapath-libvirt.rules`, that denies
  every `org.libvirt.*` action to users other than root and the trusted user
  before the distribution rules (such as Debian's `60-libvirt.rules`, which
  grants the `libvirt` group) are evaluated. Hosts without
  `/etc/polkit-1/rules.d` (such as Yocto) rely on the socket permissions alone.
- when the trusted user exists, a D-Bus policy,
  `/etc/dbus-1/system.d/seapath-libvirt-dbus.conf`, that denies the `libvirt`
  group calls to libvirt-dbus (`org.libvirt`). libvirt-dbus reaches libvirt as
  the trusted user and its packaged policy lets the `libvirt` group call it,
  which would otherwise bypass the restriction. root keeps access.

| Host                     | Socket mode | Socket group                    | `libvirtd.conf`      |
|--------------------------|-------------|---------------------------------|----------------------|
| without the trusted user | `0600`      | `root`                          | `0700`, group `root` |
| with the trusted user    | `0660`      | primary group of the user       | `0770`, same group   |

The role refuses a trusted user whose primary group is `libvirt` or `users`,
since every member of that group would then reach libvirt.

### Non-root access enabled

The role sets the socket group to `libvirt` (`0660` on the socket units,
`0770` in `libvirtd.conf`), adds the trusted user (if it exists) to the
`libvirt` group, and removes its polkit rule and D-Bus policy, so the
distribution policies apply again. Every member of the `libvirt` group, typically the
`libvirtadmin` user created by `add_libvirtadmin_user`, then becomes a root
equivalent.

### Applying a change

The role only recreates the sockets whose mode or group differs from the
policy, so a re-run with an unchanged policy restarts nothing. A daemon and all
its sockets are stopped in a single systemd transaction, then started again,
one host at a time. Running VMs keep running, but a live migration in progress
on that host at that moment is aborted.

## Live migration and console access

SEAPATH drives VM live migration and console access over the `qemu+ssh`
transport; it does not use a networked libvirt listener, as the TLS and TCP
sockets stay disabled. The `ssh` transport still terminates on the target
host's local libvirt unix socket, opened as the ssh user, so a non-root ssh
user needs non-root socket access.

- **Live migration** runs as `livemigration_user`. When it is a non-root
  account (`libvirtadmin` in the example cluster inventory), non-root socket
  access is enabled by default. VMs keep the migration user they were deployed
  with, so do not force
  `configure_libvirt_allow_non_root_libvirt_socket_access: false` on a cluster
  whose VMs migrate as a non-root user: Pacemaker would stop and restart them
  instead of migrating them.
- **`vm-mgr console`** connects as `libvirtadmin` by default in cluster mode,
  so it needs non-root socket access as well. On a cluster where it is
  disabled (`livemigration_user` unset or `root`), enable it explicitly, or use
  `vm-mgr console --ssh-user root <vm>` where root can log in over SSH between
  hypervisors. SEAPATH does not set that up, and `configure_hardening` forbids
  root SSH logins.

## Requirements

No requirement.

## Role Variables

| Variable                                               | Required | Type    | Default | Comments                                                                                              |
|--------------------------------------------------------|----------|---------|---------|-------------------------------------------------------------------------------------------------------|
| configure_libvirt_allow_non_root_libvirt_socket_access | no       | Boolean | true if `livemigration_user` is set and not `root`, else false | Allow non-root users in the libvirt group to access the (root-equivalent) libvirt read/write socket |
| configure_libvirt_socket_trusted_user                  | no       | String  | `libvirtdbus` | System user that keeps libvirt access when non-root access is disabled; ignored if missing, `""` to disable |
| configure_libvirt_socket_units                         | no       | List    | see `defaults/main.yml` | Libvirt socket units whose permissions are enforced; units missing on a host are ignored |
| configure_libvirt_tap_link_speed                       | no       | Integer | 0       | Link speed in Mb/s reported by the guest tap devices, see below. 0 keeps the default |

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
