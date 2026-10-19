# Add Libvirt administration user role

This role set up the Libvirt administration user on the cluster and configure
its ssh key exchanges.
If the user does not already exist, it will be created.
The user is named "libvirtadmin"

## Security considerations

`libvirtadmin` is added to the `libvirt` group and logs in with SSH keys only:
the role replaces the locked password marker in `/etc/shadow` (`!`) with `*`,
so password authentication stays impossible while key authentication works. A
pre-existing `libvirtadmin` account with a real password hash is not changed by
this replacement and keeps password login until the hash is cleared.

The role generates a root SSH key pair on each hypervisor and copies the
**public** key of every hypervisor in the cluster into the `authorized_keys` of
`libvirtadmin` on every hypervisor (and registers the host keys in root's
`known_hosts`). This all-to-all exchange is what lets any hypervisor open a
`qemu+ssh` connection to any other hypervisor as `libvirtadmin` for VM live
migration and console access, provided non-root socket access is enabled (see
`configure_libvirt_allow_non_root_libvirt_socket_access` below). No private key
ever leaves its host, and the distribution is scoped to `hypervisors` intersect
`cluster_machines`: nodes outside that set are not involved.

Consequences operators must accept:

- Any root account on a hypervisor can log in as `libvirtadmin` on any other
  hypervisor of the cluster. The public-key distribution is cluster-wide by
  design, because live migration may target any node.
- If `configure_libvirt_allow_non_root_libvirt_socket_access` is enabled (see
  `configure_libvirt`), `libvirtadmin` can reach the root-equivalent libvirt
  socket and thus becomes a cluster-wide root equivalent. With the secure
  default (`false`), that escalation path is closed and `libvirtadmin` can
  still SSH to any hypervisor but cannot control libvirt.

## Requirements

No requirement.

## Role Variables

No variables.

## Example Playbook

```yaml
- name: Create libvirtadmin user
  hosts: hypervisors
  gather_facts: true
  become: true
  roles:
    - { role: seapath_ansible.add_libvirtadmin_user }
```
