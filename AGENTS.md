# SEAPATH Ansible — Agent Quick Reference

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
- **Debian hardening**: `playbooks/seapath_setup_hardened_debian.yaml`
- **Example inventories**: `inventories/examples/` (cluster, standalone, vm-deployment, ovs)
- **Roles**: `roles/` — most have a `README`. Some include `molecule/` for unit tests.
- **Custom modules**: `library/`
- **Ceph integration**: `ceph-ansible/` is a **submodule** (`stable-8.0`). It is patched at setup time by `prepare.sh` from `src/ceph-ansible-patches/` and `src/ceph-ansible-site.yaml`.

## Important Ansible Config (`ansible.cfg`)

- `gathering = explicit` — facts are not gathered by default.
- `any_errors_fatal = True` — any host failure stops the playbook.
- `tags: skip = package-install` — package-install tag is skipped by default.
- `inventory = inventories/examples/seapath-cluster.yaml` — default inventory (mostly for CI).
- `roles_path = ./roles:ceph-ansible/roles` — local roles take precedence over ceph-ansible roles.

## Submodules

```
ceph-ansible                         → https://github.com/ceph/ceph-ansible.git (stable-8.0)
roles/deploy_cukinia/files/cukinia   → https://github.com/savoirfairelinux/cukinia.git
roles/deploy_python3_setup_ovs/...   → https://github.com/seapath/python3-setup-ovs.git
roles/deploy_vm_manager/files/...    → https://github.com/seapath/vm_manager.git
```

Run `git submodule update --init --force` (done by `prepare.sh`) after clone or when submodules change.

## Gotchas

- **Always run `prepare.sh` after fresh clone or when `ansible-requirements.yaml` / submodules change.** It installs galaxy roles/collections, initializes submodules, patches ceph-ansible, and downloads Cockpit plugins.
- ** ceph-ansible is excluded from lint** (see `.ansible-lint.yml` `exclude_paths`). Do not lint inside it.
- **Molecule playbooks** run from the `playbooks/` directory, not the repo root.
- **Molecule roles** are discovered dynamically — only roles with a `molecule/` directory are tested.
