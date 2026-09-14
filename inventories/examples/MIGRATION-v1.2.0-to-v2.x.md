# Inventory migration guide: v1.2.0 → v2.x

This document explains how to update your inventory files when migrating
from SEAPATH ansible v1.2.0 to v2.x (main).

The main breaking change is the replacement of **ceph-ansible** by an
internal **cephadm**-based deployment, which removes the `mons`, `osds`
and `clients` groups. The live migration user also changed.

You can compare with the updated examples in this directory:
- `seapath-cluster.yaml`
- `seapath-standalone.yaml`
- `seapath-vm-deployement.yaml`

(`seapath-ovs.yaml` has no functional change.)

---

## seapath-cluster.yaml

### Groups to remove

Ceph is no longer deployed with ceph-ansible. Remove the following groups
entirely:

- `mons` (hosts and all its vars)
- `osds` (hosts and all its vars)
- `clients` (hosts and all its vars)

Also remove the empty placeholder groups that existed mostly for
ceph-ansible:

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

### Variables to remove

- `ceph_osd_disk` and `devices` (previously in the `osds` group) — replaced
  by `ceph_osd_disks` (see below)
- In `ceph_conf_overrides.global`:
  - `osd_pool_default_pg_num`
  - `osd_pool_default_pgp_num`

  (PG autoscaling now handles placement group numbers)
- Gone along with their groups: `ceph_origin`, `cluster_network`,
  `public_network`, `monitor_address`, `configure_firewall`,
  `ntp_service_enabled`, `dashboard_enabled`, `user_config`, `rbd`,
  `pools`, `keys`, `ceph_keyring_permissions`

### Variables to change

| Variable             | Old value      | New value       |
| -------------------- | -------------- | --------------- |
| `livemigration_user` | `livemigration` | `libvirtadmin` |

Note: to setup an observer machine, you must now remove its
`ceph_osd_disks` variable instead of removing it from the `osds` group.

### New mandatory variables

Per host in `cluster_machines`, replace the old `ceph_osd_disk` of the
`osds` group with a list of disks (one OSD per disk):

```yaml
node1:
  # ...
  ceph_osd_disks:
    - "/dev/disk/by-path/pci-0000:03:00.0-scsi-0:2:1:0"
```

In `cluster_machines:vars`, add the Ceph configuration previously held by
the `mons` group:

```yaml
  vars:
    deploy_cephfs: false # Change to true to deploy cephfs on your cluster

    # Ceph configuration
    cephadm_network: "192.168.55.0/24" # IP range of your cluster.
    ceph_conf_overrides:
      global:
        osd_pool_default_size: "{{ groups['hypervisors'] | length }}"
        osd_pool_default_min_size: 1
        osd_crush_chooseleaf_type: 1
        mon_osd_min_down_reporters: 1
      mon:
        paxos prop interval: 100ms
      osd:
        osd memory target: 8076326604
```

### New optional variables

- `ptp_domain_number` (in `all.vars`) — PTP domain number (0 to 255).
  The variables `timemaster_ptp_domain_number` and
  `ptp_status_vsock_domain_number` default to it:

  ```yaml
  ptp_domain_number: 0
  timemaster_ptp_domain_number: "{{ ptp_domain_number }}"
  ptp_status_vsock_domain_number: "{{ ptp_domain_number }}"
  ```

- `grub_password` (in `all.vars`) — Debian hardening specific: GRUB
  protected password. Default password is `seapath`. Generate it with
  `grub2-mkpasswd-pbkdf2 -c 65536 / grub-mkpasswd-pbkdf2 -c 65536`.
  If not defined, the default password is used.

- `deploy_cephfs` (in `cluster_machines:vars`) — set to `true` to deploy
  CephFS on your cluster (default `false`).

- `ansible_ssh_private_key_file` — uncomment if you use a non standard
  SSH private key.

---

## seapath-standalone.yaml

### Groups to remove

Same empty placeholder groups as for the cluster inventory:

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

### New mandatory variables

None.

### New optional variables

- `grub_password` (in `all.vars`) — see above.
- `ansible_ssh_private_key_file` — uncomment if you use a non standard
  SSH private key.

---

## seapath-vm-deployement.yaml

### Groups to remove / variables to change

None.

### New mandatory variables

Per VM host, add `live_migration`:

```yaml
seapath-vm:
  # ...
  live_migration: true # Enable live_migration for this VM
```

### New optional variables

- `ansible_ssh_private_key_file` (in `VMs:vars`) — uncomment if you use a
  non standard SSH private key.

---

## seapath-ovs.yaml

No change required.
