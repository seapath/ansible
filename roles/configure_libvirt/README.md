# Configure Libvirt Role

This enables and starts the libvirtd service and associated socket.

The role always generates `/etc/libvirt/libvirtd.conf` with the TLS and TCP
listeners disabled and `host_uuid_source = "machine-id"`.

## Non-root socket access

Non-root access to the libvirt socket is disabled by default
(`configure_libvirt_allow_non_root_libvirt_socket_access: false`). In that case
the role sets the read and write socket permissions to `0700` and the socket
group to `root`, so only root can control libvirtd.

The read/write libvirt socket is **root-equivalent**: whoever can reach it can
start, stop, reconfigure or open the console of every VM, attach host devices
and reach host files through the VM definitions. Granting that access to a
non-root account therefore turns that account into a cluster-wide root
equivalent, which is why it is opt-in.

Set `configure_libvirt_allow_non_root_libvirt_socket_access: true` only when a
non-root account (typically the `libvirtadmin` user created by
`add_libvirtadmin_user`) must drive libvirt locally. The role then sets the
socket group to `libvirt` with `0770` permissions, as libvirt expects for
group-based access.

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

## Example Playbook

```yaml
- hosts: hypervisors
  become: true
  roles:
    - { role: seapath_ansible.configure_libvirt }
```
