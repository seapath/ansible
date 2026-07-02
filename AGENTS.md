# SEAPATH Ansible — Agent Quick Reference

## What is SEAPATH

SEAPATH (LF Energy) is a real-time virtualization platform for **electrical
substation automation**: it runs protection/automation functions (IEC 61850 —
Sampled Values, GOOSE) as VMs and containers on standard servers, with hard
latency guarantees. This repo is the **configuration layer**: Ansible playbooks
that turn freshly imaged machines (Debian ISO or Yocto image, built in sibling
repos) into standalone hypervisors or a highly-available cluster.

## System architecture (mental model)

A SEAPATH machine is a Linux KVM hypervisor with:

- **libvirt/QEMU** guests, disks on **Ceph RBD** in cluster mode (deployed via
  `cephadm`), local disks in standalone mode.
- **Open vSwitch** networking (+ optional SR-IOV) for guest traffic; a separate
  administration network.
- **Real-time tuning**: isolated CPUs (`isolcpus`), tuned profiles, NIC IRQ
  affinity pinning, dynamic per-VM CPU pinning (`deploy_seapath_alloc`).
  Latency is validated with cyclictest/cukinia in CI.
- **PTP time sync** (timemaster/linuxptp), propagated to guests.
- Cluster mode: **3+ nodes** with **Corosync/Pacemaker** HA; VMs are cluster
  resources managed through **vm_manager** (submodule, Python CLI).
- Observability/admin: Cockpit, SNMP, syslog-ng, Prometheus node_exporter
  textfile collectors.

Inventory groups you will meet everywhere: `hypervisors`, `cluster_machines`,
`standalone_machine`, `observers`, `mons`/`osds`/`clients` (Ceph), `VMs`.

## Role map (roles/ — ~60 roles, grouped by prefix)

| Prefix / role | Purpose |
|---|---|
| `network_*` | OVS bridges, systemd-networkd/netplan, cluster network, SR-IOV |
| `cephadm*`, `ceph_*` | Ceph deployment and expansion |
| `configure_*` | Host config: hypervisor RT tuning, libvirt, HA, hardening, NIC IRQ affinity |
| `deploy_*` | Payloads: VMs, vm_manager, seapath_alloc (CPU pinning), cukinia tests, Cockpit |
| `ci_*` | CI-only helpers (snapshots, test images) |
| `timemaster`, `snmp`, `syslog_ng_client`, `iptables` | Time sync, monitoring, logging, firewall |
| `update`, `backup_restore`, `vmmgrapi` | Lifecycle: updates, backup, VM manager REST API |

Key playbooks: `seapath_setup_main.yaml` (full setup),
`cluster_setup_{cephadm,ha,libvirt}.yaml`, `deploy_vms_{cluster,standalone}.yaml`,
`replace_machine_*.yaml` (node replacement), `seapath_update_*.yaml`.

## Domain invariants (read before hunting bugs)

- **Real time is the product.** Anything touching isolated CPUs, tuned, IRQ
  affinity, CPU pinning or PTP can silently break latency guarantees. The RT
  invariants of dynamic pinning are documented in
  `roles/deploy_seapath_alloc/ARCHITECTURE.md` — read it before touching that
  role; it also has a pytest suite (see its README).
- **Playbooks re-run on live substations.** Idempotence matters: unnecessary
  `changed` states can trigger handlers that restart services under live VMs.
- **A failing host aborts everything** (`any_errors_fatal = True`) and facts
  are **not** gathered unless a play asks (`gathering = explicit`).
- Licensing: SPDX headers, Apache-2.0 for code, CC-BY-4.0 for docs.

## Development Environment

- **Primary toolchain**: `cqfd` (Docker wrapper). All commands should be prefixed with `cqfd run` unless running natively.
- **Ansible version**: Exactly `2.16.x` is required. `prepare.sh` enforces this.
- **One-time setup**:
  ```bash
  cqfd init           # build the dev container
  cqfd -b prepare     # install galaxy deps, submodules, patches, plugins
  ```
- **Without cqfd**: install `ansible-core~=2.16.0`, `netaddr`, `six`, `rsync`, then run `./prepare.sh`.

## Lint / Format

- **Lint**: `cqfd -b lint`  (or `ansible-lint` natively)
- **Format**: `cqfd -b format`  (or `ansible-lint --fix=yaml` natively)
- **Pre-commit**: `pre-commit install` — runs `ansible-lint v26.1.1` on every commit.
- **Config**:
  - `.ansible-lint.yml` — skips `role-name`, warns on `no-handler` / `no-changed-when`
  - `.yamllint` — line-length max 1024 (allows ansible-lint --fix=yaml to work)

## Testing

- **Run all molecule tests**: `tox -m molecule`
- **Role tests only**: `tox -ie molecule-roles`  (runs `scripts/run-molecule-roles.sh`)
- **Playbook tests only**: `tox -e molecule-playbooks`  (runs from `playbooks/` dir)
- **Single role**: `cd roles/<role> && molecule test --all`
- **Backend**: Podman. Molecule tests require podman installed.

## CI Pipeline (PRs to `main`)

```
qa (ansible-lint) → molecule → debian / yocto / centos / oraclelinux integration
```

Integration tests run on self-hosted runners and use the external `seapath/ci` repo.

## Repo Structure & Entrypoints

- **Main setup playbook**: `playbooks/seapath_setup_main.yaml`
- **Debian hardening**: `playbooks/seapath_setup_hardening.yaml`
- **Example inventories**: `inventories/examples/` (cluster, standalone, vm-deployment, ovs)
- **Roles**: `roles/` — most have a `README`. Some include `molecule/` for unit tests.
- **Custom modules**: `library/`

## Important Ansible Config (`ansible.cfg`)

- `gathering = explicit` — facts are not gathered by default.
- `any_errors_fatal = True` — any host failure stops the playbook.
- `tags: skip = package-install` — package-install tag is skipped by default.
- `inventory = inventories/examples/seapath-cluster.yaml` — default inventory (mostly for CI).

## Submodules

```
roles/deploy_cukinia/files/cukinia   → https://github.com/savoirfairelinux/cukinia.git
roles/deploy_python3_setup_ovs/...   → https://github.com/seapath/python3-setup-ovs.git
roles/deploy_vm_manager/files/...    → https://github.com/seapath/vm_manager.git
```

Run `git submodule update --init --force` (done by `prepare.sh`) after clone or when submodules change.

## Gotchas

- **Always run `prepare.sh` after fresh clone or when `ansible-requirements.yaml` / submodules change.** It installs galaxy roles/collections, initializes submodules, and downloads Cockpit plugins.
- **Molecule playbooks** run from the `playbooks/` directory, not the repo root.
- **Molecule roles** are discovered dynamically — only roles with a `molecule/` directory are tested.
