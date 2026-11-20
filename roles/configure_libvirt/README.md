# Configure Libvirt Role

This enables and starts the libvirtd service and associated socket.

The role always generates `/etc/libvirt/libvirtd.conf` with the TLS and TCP
listeners disabled and `host_uuid_source = "machine-id"`.

## Non-root socket access

Non-root access to the libvirt socket is disabled by default
(`configure_libvirt_allow_non_root_libvirt_socket_access: false`). In that case
only root can reach libvirt. The role enforces this on three layers:

- `libvirtd.conf`: `unix_sock_*` permissions `0700`, group `root`. Only a
  libvirtd that is not socket-activated reads these settings.
- systemd drop-ins on every libvirt socket unit listed in
  `configure_libvirt_socket_units` (`libvirtd*.socket` on Debian, the modular
  `virt*d*.socket` daemons on OracleLinux): `SocketMode=0600`,
  `SocketGroup=root`. This is what restricts the sockets on socket-activated
  hosts, where the distribution ships them as `0666`.
- a polkit rule, `/etc/polkit-1/rules.d/10-seapath-libvirt.rules`, that denies
  every `org.libvirt.*` action to non-root users before the distribution
  rules (such as Debian's `60-libvirt.rules`, which grants the `libvirt`
  group) are evaluated. Hosts without `/etc/polkit-1/rules.d` (such as Yocto)
  rely on the socket permissions alone.

Changing this setting recreates the affected sockets: the role only restarts
the daemons whose sockets have a mode or group that differs from the policy,
so a re-run with an unchanged policy restarts nothing. A daemon and all its
sockets are stopped in a single systemd transaction, then started again, one
host at a time. Running VMs keep running, but a live migration in progress on
that host at that moment is aborted.

The read/write libvirt socket is **root-equivalent**: whoever can reach it can
start, stop, reconfigure or open the console of every VM, attach host devices
and reach host files through the VM definitions. Granting that access to a
non-root account therefore turns that account into a cluster-wide root
equivalent, which is why it is opt-in.

Set `configure_libvirt_allow_non_root_libvirt_socket_access: true` only when a
non-root account (typically the `libvirtadmin` user created by
`add_libvirtadmin_user`) must drive libvirt locally. The role then sets the
socket group to `libvirt` (`0770` in `libvirtd.conf`, `0660` on the socket
units) and removes its polkit rule, so the distribution polkit policy applies
again.

## Live migration and console access

SEAPATH drives VM live migration and console access over the `qemu+ssh`
transport as the account configured by `livemigration_user` (for example
`libvirtadmin` in the example cluster inventory); it does not use a networked
libvirt listener, as the TLS and TCP sockets stay disabled.

The `ssh` transport still terminates on the target host's local libvirt unix
socket, opened as the ssh user. A **non-root** `livemigration_user` therefore
needs the local socket access to be enabled: when such a user is configured,
set `configure_libvirt_allow_non_root_libvirt_socket_access: true` on the
hypervisors. Live migration performed as `root` works with the default.
The example cluster inventory
(`inventories/examples/seapath-cluster.yaml`) sets this variable to `true`
because it defines `livemigration_user: libvirtadmin`.

## Requirements

No requirement.

## Role Variables

| Variable                                               | Required | Type    | Default | Comments                                                                                              |
|--------------------------------------------------------|----------|---------|---------|-------------------------------------------------------------------------------------------------------|
| configure_libvirt_allow_non_root_libvirt_socket_access | no       | Boolean | false   | Allow non-root users in the libvirt group to access the (root-equivalent) libvirt read/write socket   |
| configure_libvirt_socket_units                         | no       | List    | see `defaults/main.yml` | Libvirt socket units whose permissions are enforced; units missing on a host are ignored |

## Example Playbook

```yaml
- hosts: hypervisors
  become: true
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
