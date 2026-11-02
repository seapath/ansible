# Stage VM Disk Role

Stages a disk image on the hypervisor from a single disk entry (`stage_vm_disk_source`): a path is copied from the Ansible control node, a URL is downloaded directly on the target. For local sources an optional checksum is verified after the copy; for remote sources the checksum is mandatory and verified by the download. A file that does not match its checksum never remains at the destination; an existing file there is not preserved for recovery.

This role is an internal building block shared by `deploy_vms_cluster` and `deploy_vms_standalone`, which use it for both system disks and additional disks. It is not meant to be used directly from a playbook.

## Requirements

No requirement.

## Role Variables

| Variable                            | Required | Type           | Default               | Comments                                                                                                                                                                                                                                                                                                                                                                    |
|-------------------------------------|----------|----------------|-----------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| stage_vm_disk_source                | No*      | String or Dict | ""                    | Disk entry straight from the inventory: a path string, or a dict with `path` plus optional checksum keys (`sha512`/`sha384`/`sha256`, the strongest given is used) and an optional `label` (ignored here, see the `normalize` entry point). A `path` on the control node is copied to the target; a `path` that is a URL (`http`/`https`/`ftp`/`ftps`) is fetched on the target and requires a checksum. |
| stage_vm_disk_fallback_source       | No*      | String         | ""                    | Local path used when `stage_vm_disk_source` is empty. If neither provides a source, the role fails.                                                                                                                                                                                                                                                                         |
| stage_vm_disk_destination           | No*      | String         | directory + file name | Path on the target host where the disk image is written. Defaults to `stage_vm_disk_destination_directory` plus the file name of the resolved source (local, remote or fallback; for a URL the last path segment, without query string); one of the two must be provided.                                                                                                                                                          |
| stage_vm_disk_destination_directory | No*      | String         | ""                    | Target directory used to derive `stage_vm_disk_destination` from the source's base name                                                                                                                                                                                                                                                                                     |
| stage_vm_disk_label                 | No       | String         | destination           | Display name used in task names and error messages (e.g. the VM name)                                                                                                                                                                                                                                                                                                       |
| stage_vm_disk_remote_tmp            | No       | String         | "/tmp"                | Value for `ansible_remote_tmp` while staging (upload staging directory for local copies, download temp directory for remote fetches)                                                                                                                                                                                                                                        |
| stage_vm_disk_validate_certs        | No       | Bool           | true                  | Set to `false` to skip TLS certificate validation when fetching a remote source (e.g. an internal server whose CA is not trusted on the target). The mandatory checksum still guarantees integrity.                                                                                                                                                                         |

\* One of each pair must be set: `stage_vm_disk_source` or `stage_vm_disk_fallback_source` for the source, `stage_vm_disk_destination` or `stage_vm_disk_destination_directory` for the destination.

## Entry point `normalize`

Converts a mixed disk list — path strings and dicts with `path` plus optional flat checksum keys (`sha512`/`sha384`/`sha256`) and an optional `label` — into a normalized dict list. Entries whose `path` is a URL (`http`/`https`/`ftp`/`ftps`) are classified as remote. The `label` (letters, digits, `_` and `-` only) is passed through for consumers that reflect it in the staged file name, e.g. `deploy_vms_standalone` naming additional disks `<vm>_data_<index>_<label>.qcow2`. Invalid entries fail with a descriptive message.

Staging itself does not need this entry point (pass raw entries via `stage_vm_disk_source` instead); use it when the normalized data is needed as such, e.g. to derive the staged file names for a libvirt template.

| Variable            | Required | Type   | Comments                                                     |
|---------------------|----------|--------|--------------------------------------------------------------|
| stage_vm_disk_disks | Yes      | List   | Mixed list of path strings and `{path, <algo>: <hex>}` dicts |
| stage_vm_disk_label | Yes      | String | Display name used in task names and error messages           |

Sets the fact `stage_vm_disk_normalized_disks`: one dict per entry with `file` (file name of the source, for a URL the last path segment without query string), `label` (empty string if not given), `local_source`, `remote_source` (exactly one non-empty) and `checksum`. The main entry point takes the raw entries, not these dicts.

## Example

```yaml
- name: "Stage system disk on target for {{ item }}"
  ansible.builtin.include_role:
    name: stage_vm_disk
  vars:
    stage_vm_disk_label: "{{ item }}"
    stage_vm_disk_source: "{{ hostvars[item].vm_disk | default('') }}"
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
