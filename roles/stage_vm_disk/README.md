# Stage VM Disk Role

Stages a disk image on the hypervisor, either by copying it from the Ansible control node (`stage_vm_disk_local_source`) or by downloading it directly on the target from a remote URL (`stage_vm_disk_remote_source`). For local sources an optional checksum is verified after the copy and a mismatching file is removed from the target; for remote sources the checksum is mandatory and verified once during the download (nothing is written to the destination on a mismatch).

This role is an internal building block shared by `deploy_vms_cluster` and `deploy_vms_standalone`, which use it for both system disks and additional disks. It is not meant to be used directly from a playbook.

## Requirements

No requirement.

## Role Variables

| Variable                            | Required | Type           | Default               | Comments                                                                                                                                                                                                                                                                                            |
|-------------------------------------|----------|----------------|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| stage_vm_disk_source                | No       | String or Dict | ""                    | Raw disk entry straight from the inventory: a path string, or a dict with `path` plus optional flat checksum keys (`sha512`/`sha384`/`sha256`) and an optional `label` (ignored here, see the `normalize` entry point). A `path` that is a URL (`http`/`https`/`ftp`/`ftps`) is fetched on the target. Provides the defaults for the three explicit source variables below. |
| stage_vm_disk_local_source          | No*      | String         | from `source`         | Path to the disk image on the Ansible control node. Mutually exclusive with `stage_vm_disk_remote_source`.                                                                                                                                                                                          |
| stage_vm_disk_remote_source         | No*      | String         | from `source`         | URL (`http`/`https`/`ftp`/`ftps`) of the disk image, fetched directly on the target. Requires `stage_vm_disk_checksum`.                                                                                                                                                                             |
| stage_vm_disk_fallback_source       | No       | String         | ""                    | Local path used when neither a local nor a remote source is set. A remote source wins over the fallback. If no source resolves at all, the role fails.                                                                                                                                              |
| stage_vm_disk_checksum              | No       | Dict           | from `source`         | Dict `{<algo>: <hex>, ...}` to verify the disk. Required for remote sources, optional for local ones. May list multiple algorithms; the strongest available is used (preference: `sha512` > `sha384` > `sha256`).                                                                                   |
| stage_vm_disk_destination           | No*      | String         | directory + file name | Path on the target host where the disk image is written. Defaults to `stage_vm_disk_destination_directory` plus the base name of the resolved source (local, remote or fallback); one of the two must be provided.                                                                                  |
| stage_vm_disk_destination_directory | No*      | String         | ""                    | Target directory used to derive `stage_vm_disk_destination` from the source's base name                                                                                                                                                                                                             |
| stage_vm_disk_label                 | No       | String         | destination           | Display name used in task names and error messages (e.g. the VM name)                                                                                                                                                                                                                               |
| stage_vm_disk_remote_tmp            | No       | String         |                       | Value for `ansible_remote_tmp` while staging (upload staging directory for local copies, download temp directory for remote fetches)                                                                                                                                                                |
| stage_vm_disk_validate_certs        | No       | Bool           | true                  | Set to `false` to skip TLS certificate validation when fetching a remote source (e.g. an internal server whose CA is not trusted on the target). The mandatory checksum still guarantees integrity.                                                                                                  |

## Entry point `normalize`

Converts a mixed disk list — path strings and dicts with `path` plus optional flat checksum keys (`sha512`/`sha384`/`sha256`) and an optional `label` — into a normalized dict list. Entries whose `path` is a URL (`http`/`https`/`ftp`/`ftps`) are classified as remote. The `label` (letters, digits, `_` and `-` only) is passed through for consumers that reflect it in the staged file name, e.g. `deploy_vms_standalone` naming additional disks `<vm>_data_<index>_<label>.qcow2`. Invalid entries fail with a descriptive message.

Staging itself does not need this entry point (pass raw entries via `stage_vm_disk_source` instead); use it when the normalized data is needed as such, e.g. to derive the staged file names for a libvirt template.

| Variable            | Required | Type   | Comments                                                     |
|---------------------|----------|--------|--------------------------------------------------------------|
| stage_vm_disk_disks | Yes      | List   | Mixed list of path strings and `{path, <algo>: <hex>}` dicts |
| stage_vm_disk_label | Yes      | String | Display name used in task names and error messages           |

Sets the fact `stage_vm_disk_normalized_disks`: one dict per entry with `file` (basename of the source), `label` (empty string if not given), `local_source`, `remote_source` (exactly one non-empty) and `checksum` — ready to be passed straight into the main entry point.

## Example

```yaml
- name: "Stage system disk on target for {{ item }}"
  ansible.builtin.include_role:
    name: stage_vm_disk
  vars:
    stage_vm_disk_label: "{{ item }}"
    stage_vm_disk_source: "{{ hostvars[item].vm_disk | default('') }}"
    stage_vm_disk_checksum: "{{ hostvars[item].vm_disk_checksum | default({}) }}"
    stage_vm_disk_destination: "/var/lib/libvirt/images/{{ item }}.qcow2"

- name: "Stage additional disks for {{ item }}"
  ansible.builtin.include_role:
    name: stage_vm_disk
  vars:
    stage_vm_disk_destination_directory: /var/lib/libvirt/images
    stage_vm_disk_source: "{{ add_disk }}"
  loop: "{{ hostvars[item].additional_disk | default([]) }}"
  loop_control:
    loop_var: add_disk
```
