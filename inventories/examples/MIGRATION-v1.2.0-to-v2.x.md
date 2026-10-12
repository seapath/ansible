# Inventory migration guide: v1.2.0 → v2.x

This document explains how to update your inventory files when migrating
from SEAPATH ansible v1.2.0 to v2.x.

The main breaking change is the replacement of **ceph-ansible** by an
internal **cephadm**-based deployment, introduced in v2.0.0. The live
migration user also changed.

The guide has two parts:

1. **Required changes, v1.2.0 to v2.0.x**: what your inventory must change
   to work with the v2.0.x releases. The v2.0.2 example inventories show
   the result.
2. **Optional cleanup, v2.0.x to `main` (future v2.1)**: a minor release
   does not break existing inventories, so an inventory following part 1
   keeps working. The `main` example inventories go further and drop the
   `mons`, `osds` and `clients` groups. This part is a cleanup, not a
   requirement.

An inventory following part 2 does not work on v2.0.x, which iterates
over `groups['osds']`.

You can compare with the example inventories of this directory, in the
version you target:
- `seapath-cluster.yaml`
- `seapath-standalone.yaml`
- `seapath-vm-deployement.yaml`

(`seapath-ovs.yaml` has no functional change.)

---

# Part 1: required changes, v1.2.0 to v2.0.x

## seapath-cluster.yaml

### Variables to change

| Variable             | Old value       | New value      |
| -------------------- | --------------- | -------------- |
| `livemigration_user` | `livemigration` | `libvirtadmin` |

### Variables to remove

In `ceph_conf_overrides.global` (`mons` group):

- `osd_pool_default_pg_num`
- `osd_pool_default_pgp_num`

PG autoscaling now handles placement group numbers, and keeping these
options makes the pool creation fail with `ERANGE`.

### New mandatory variables

- `cephadm_network` (in the `mons` group vars): the Ceph network. In the
  example inventory it follows `public_network`:

  ```yaml
  mons:
    vars:
      cephadm_network: "{{ public_network }}"
  ```

- `grub_password` (in `all.vars`): the GRUB protected password. It is
  required on every distribution that runs `seapath_setup_hardening.yaml`.
  Generate it with `grub-mkpasswd-pbkdf2 -c 65536` on Debian, or
  `grub2-mkpasswd-pbkdf2 -c 65536` on the other distributions. The hash
  shipped in the example inventory is the hash of the `seapath` password.

### Recommended changes

- In the `clients` group, quote the value of `pg_autoscale_mode` (`"on"`
  instead of `on`), otherwise YAML reads it as a boolean.
- The empty placeholder groups that existed mostly for ceph-ansible are
  removed from the example inventory:

  ```yaml
  grafana-server:
  iscsigws:
  iscsi-gws:
  mdss:
  mgrs:
  nfss:
  rbdmirrors:
  rgwloadbalancers:
  rgws:
  ```

### New optional variables

- `ptp_domain_number` (in `all.vars`): PTP domain number (0 to 255).
  `timemaster_ptp_domain_number` and `ptp_status_vsock_domain_number`
  both default to `0`; add these two lines so they follow
  `ptp_domain_number`:

  ```yaml
  ptp_domain_number: 0
  timemaster_ptp_domain_number: "{{ ptp_domain_number }}"
  ptp_status_vsock_domain_number: "{{ ptp_domain_number }}"
  ```

- `deploy_cephfs` (in `cluster_machines:vars`): set to `true` to deploy
  CephFS on your cluster (default `false`).

## seapath-standalone.yaml

### New mandatory variables

`grub_password` (in `all.vars`): GRUB protected password, required on
every distribution. See the cluster section above.

### Recommended changes

Remove the same empty placeholder groups as for the cluster inventory.

## seapath-vm-deployement.yaml

### New optional variables

- `live_migration` (per VM host, in `VMs`): set to `true` to enable live
  migration for that VM (default `false`). In the example inventory it is
  set on `rtvm` only:

  ```yaml
  rtvm:
    # ...
    live_migration: true # Enable live migration for this VM
  ```

## seapath-ovs.yaml

No change required.

---

# Part 2: optional cleanup, v2.0.x to `main`

These changes are not required. They make your inventory match the `main`
examples, but an inventory using them no longer works on v2.0.x.

## seapath-cluster.yaml

### Groups to remove

Ceph is deployed by the `cephadm` role only. Remove the following groups
entirely:

- `mons` (hosts and all its vars)
- `osds` (hosts and all its vars)
- `clients` (hosts and all its vars)

Before removing them, move what you need out of `mons` and `osds` as
described below.

### Variables to remove

- `devices` (previously in the `osds` group), and the `ceph_osd_disk` of
  the `osds` group: the disks are now declared per host in
  `cluster_machines` with `ceph_osd_disks` (see below). `ceph_osd_disk` is
  still accepted there as a shorthand for a one-element `ceph_osd_disks`
  list.
- Gone along with their groups: `ceph_origin`, `cluster_network`,
  `public_network`, `monitor_address`, `configure_firewall`,
  `ntp_service_enabled`, `dashboard_enabled`, `user_config`, `rbd`,
  `pools`, `keys`, `ceph_keyring_permissions`

Note: to setup an observer machine, you must now remove its
`ceph_osd_disks` variable instead of removing it from the `osds` group.

### Variables to move

Per host in `cluster_machines`, replace the old `ceph_osd_disk` of the
`osds` group with a list of disks (one OSD per disk):

```yaml
cluster_machines:
  hosts:
    node1:
      # ...
      ceph_osd_disks:
        - "/dev/disk/by-path/pci-0000:03:00.0-scsi-0:2:1:0"
```

In `cluster_machines:vars`, move `cephadm_network` from the `mons` group.
It no longer needs `public_network`:

```yaml
cluster_machines:
  vars:
    cephadm_network: "192.168.55.0/24" # IP range of your cluster.
```

`ceph_conf_overrides` is optional: move it to `cluster_machines:vars` if
you want to keep the Ceph options previously set in the `mons` group,
grouped by section. The example inventory keeps the previous values:

```yaml
cluster_machines:
  vars:
    ceph_conf_overrides:
      global:
        osd_pool_default_size: "{{ groups['hypervisors'] | length }}"
        osd_pool_default_min_size: 1
        osd_crush_chooseleaf_type: 1
        mon_osd_min_down_reporters: 1
      mon:
        auth_allow_insecure_global_id_reclaim: false
      osd:
        osd memory target: 8076326604
```

### Shared OSD disk (`lvm_volumes`)

If your `osds` hosts defined `lvm_volumes` to share the OSD disk with
another partition, `ceph_prepare_installation` still handles it, but it is
deprecated. Move `ceph_osd_disk` and `lvm_volumes` to the matching host of
`cluster_machines`. For a new inventory, create the logical volume outside
of the playbooks and list it in `ceph_osd_disks` instead. See
`roles/ceph_prepare_installation/README.md`.

### New optional variables

- `ansible_ssh_private_key_file`: uncomment if you use a non standard
  SSH private key.

## seapath-standalone.yaml

### New optional variables

- `ansible_ssh_private_key_file`: uncomment if you use a non standard
  SSH private key.

## seapath-vm-deployement.yaml

### New optional variables

- `ansible_ssh_private_key_file` (in `VMs:vars`): uncomment if you use a
  non standard SSH private key.

## seapath-ovs.yaml

No change required.
