# Backup-restore Role

This role installs the backup-restore utility on cluster machines. The
utility backs up to a remote server, and restores, the two kinds of workload a
SEAPATH cluster runs on Ceph RBD (cluster mode only): the guests (VMs) of
`vm_manager`, and the container workloads of `deploy_containers_cluster`.
Each is backed up whole, so that it can be restored on a cluster that never
had it.

## Guests

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

## Container workloads

A container workload of `deploy_containers_cluster` keeps what it writes on an
RBD image named after it, `rbd/<name>`, and the role records its definition
in the metadata of that image (`seapath.definition`): the entry as the
inventory declares it and the text of the quadlets and configuration files it
names, as `vm_manager` records the XML of a guest on its disk. A backup holds
that image, its metadata and the container images the workload runs, which is
enough to declare and deploy the workload again on a cluster that never had
it. The workloads are recognised by the `seapath.images` key the role records in the
metadata of their image (`get_containers.py`): a workload that declares no
`images` has no such key and is not backed up. The images the role put aside
when it recreated a workload are left out.

`include_vm` and `exclude_vm` apply to workload names as to guest names: both
are Pacemaker resources and share one namespace.

A full backup snapshots each image and exports it as a qcow2, and an
incremental backup exports an RBD diff against the latest snapshot a backup
took. They sit under `containers/<name>/` in the full backup directory, with
the image metadata of every date as `<date>.json`, and the container images
the workload runs, `podman image save` of each name in `seapath.images`, with
`/`, `:` and `@` written `_`:

```
202603110733/containers/nginx/202603110733.qcow2
202603110733/containers/nginx/202603110733.json
202603110733/containers/nginx/202603110733_202603110836.diff
202603110733/containers/nginx/202603110836.json
202603110733/containers/nginx/images/public.ecr.aws_nginx_nginx_1.31.5.tar
```

An image is saved once per full backup, from the node the backup runs on; an
incremental backup adds the images a new version brought. One the node does
not have is reported and left out.

Only the snapshots of previous backups are removed, never the ones
`deploy_containers_cluster` takes before a new version, and the image is not
sparsified. The workload runs meanwhile, so the snapshot holds what a power cut
would leave, as the role's own snapshots do.

`restore_container.sh` (menu entry "restore container") stops the workload
with `crm --wait resource stop`, puts its current image aside as
`<name>.<date>-restore`, which `deploy_containers_cluster` prunes with the
images it puts aside itself, recreates the image from the backup up to the
chosen date with its metadata, the definition included, and starts the
workload again unless it was stopped. The metadata are written through the
Ceph bindings (`restore_metadata.py`), since a definition can exceed what one
argument of `rbd image-meta set` holds. The saved container images are left in
`<local_tmp_dir>/images/`. It refuses an image a node still has mapped. On a cluster being
rebuilt, restore the image before deploying the workload: the role keeps an
image that exists rather than creating an empty one. A workload the inventory
no longer declares is declared again from `seapath.definition`, its files
written where the entry names them and its images where `archive` names them. The workload runs the
version the inventory gives it, which may be newer than the state restored:
to go back to the version too, revert the inventory first.

## Configuration

The tool is configured through `/etc/backup-restore.conf`. Set any of the
variables below and the role renders that file from the inventory at every
convergence, on every machine it plays; leave them all unset and the file is
created empty and filled by the `backup-restore.sh` menu on the machine, which
is how the role has always behaved. `include_vm` and `exclude_vm` are extended
regular expressions matched against the names of the guests and of the
container workloads alike, both being Pacemaker resources in one namespace.
They keep the names they had when only guests were backed up, since they are
the keys of that file on every machine already configured.

The machines reach the backup server over SSH as root, without a password.
The role can create a key dedicated to that and trust the server's host key;
installing the public key in the server's `authorized_keys` stays the job of
whoever administers that server, for example with `ssh-copy-id`.

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
| `backup_restore_include_vm` | An extended regular expression matched against the names of the guests and of the container workloads. Unset means all of them |
| `backup_restore_exclude_vm` | An extended regular expression, applied after the one above, to the same names. Unset means nothing is left out |
| `backup_restore_ssh_key` | A path, such as `/root/.ssh/backup_restore_ed25519`. The role generates an ed25519 key pair there once, and `remote_shell` then defaults to `ssh -i <path>`. The public half, `<path>.pub`, is what the backup server's `authorized_keys` must hold |
| `backup_restore_remote_host_keys` | The backup server's host keys, as `known_hosts` lines (`<host> <type> <key>`, with `[host]:port` for another port). They are added to root's `known_hosts` |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.backup_restore }
```
