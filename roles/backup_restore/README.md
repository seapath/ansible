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

The tool is configured through `/etc/backup-restore.conf`. Set any of the
variables below and the role renders that file from the inventory at every
convergence, on every machine it plays; leave them all unset and the file is
created empty and filled by the `backup-restore.sh` menu on the machine, which
is how the role has always behaved. `include_vm` and `exclude_vm` are extended
regular expressions matched against guest names.

## Requirements

no requirement.

## Role Variables

| Variable | Description |
|---|---|
| `backup_restore_remote_serv` | The account the backups are pushed to, as ssh and rsync take it before the colon: `[user@]host` |
| `backup_restore_remote_dir` | Where the full backup directories live on that server. It ends with a slash: the scripts glue the date onto it |
| `backup_restore_local_dir` | Where a full backup is assembled before it is sent. A full backup empties it with `rm -rf`, so it must be a directory of its own and must end with a slash. The role creates it, readable by root only |
| `backup_restore_local_tmp_dir` | Where a restore downloads what it needs before applying it. Emptied at the start of every restore. The role creates it, readable by root only |
| `backup_restore_remote_shell` | How the machines reach the backup server. Defaults to `ssh`, and takes its options: `ssh -p 2222` |
| `backup_restore_include_vm` | An extended regular expression matched against guest names. Unset means every guest |
| `backup_restore_exclude_vm` | An extended regular expression, applied after the one above. Unset means nothing is left out |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.backup_restore }
```
