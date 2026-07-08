# Backup-restore Role

This role installs the backup-restore utility on cluster machines. The
utility backs up VMs stored in Ceph RBD (cluster mode only) to a remote
server, and restores them.

For each guest, the backup covers:

- the system disk (`system_<guest>` RBD image);
- its additional disks (`data_<guest>_<n>` RBD images), if any;
- the libvirt XML and all RBD image metadata of the system disk.

Full backups export every disk as a qcow2 image; incremental backups export
RBD diffs against the latest snapshot. On restore, the VM is recreated with
`vm-mgr create` (including its additional disks), diffs are re-applied up to
the chosen date, and metadata is restored.

Note: an additional disk added to a VM after the latest full backup cannot
be backed up incrementally; the incremental backup skips it with a warning
until a new full backup is made.

The tool is configured through `/etc/backup-restore.conf` (managed by the
`backup-restore.sh` menu). `include_vm` and `exclude_vm` are extended
regular expressions matched against guest names.

## Requirements

no requirement.

## Role Variables

no variable

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.backup_restore }
```
