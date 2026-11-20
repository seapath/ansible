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

Only root can reach libvirt. The role enforces this on three layers:

- `libvirtd.conf`: `unix_sock_*` permissions `0700`, group `root`. Only a
  libvirtd that is not socket-activated reads these settings.
- systemd drop-ins on every libvirt socket unit listed in
  `configure_libvirt_socket_units` (`libvirtd*.socket` on Debian and SLES, the
  modular `virt*d*.socket` daemons on OracleLinux). This is what restricts the
  sockets on socket-activated hosts, where the distribution ships them as
  `0666`: `SocketMode=0600`, `SocketGroup=root`.
- a polkit rule, `/etc/polkit-1/rules.d/10-seapath-libvirt.rules`, that denies
  every `org.libvirt.*` action to non-root users before the distribution
  rules (such as Debian's `60-libvirt.rules`, which grants the `libvirt`
  group) are evaluated. Hosts without `/etc/polkit-1/rules.d` (such as Yocto)
  rely on the socket permissions alone.

### Non-root access enabled

The role sets the socket group to `libvirt` (`0660` on the socket units,
`0770` in `libvirtd.conf`) and removes its polkit rule, so the distribution
polkit policy applies again. Every member of the `libvirt` group, typically the
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
| configure_libvirt_socket_units                         | no       | List    | see `defaults/main.yml` | Libvirt socket units whose permissions are enforced; units missing on a host are ignored |

## Example Playbook

```yaml
- hosts: hypervisors
  become: true
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
