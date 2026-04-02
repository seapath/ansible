# Upload extra files Role

This role uploads additional files and archives to target hosts.
It ensures destination directories exist before upload and extraction.

## Requirements

No specific requirement.

## Role Variables

| Variable                       | Required | Type | Default | Comments |
|--------------------------------|----------|------|---------|----------|
| `upload_extra_files_upload_files`                 | No       | List | `[]`    | List of files/archives to upload. Each item supports `src`, `dest`, optional `owner`, `group`, `mode`, optional `extract` (boolean), and optional `dir_mode`. |
| `upload_extra_files_commands_to_run_after_upload` | No       | List | `[]`    | Shell commands executed after all uploads. |

## `upload_extra_files_upload_files` item format

- `src`: Local source file path.
- `dest`: Remote destination path.
- `extract`: When `true`, the role uses `unarchive` and treats `dest` as destination directory.
- `owner` / `group`: Ownership of created content (default `root:root`).
- `mode`: Permission mode for copied or extracted files (default `0644`).
- `dir_mode`: Permission mode for created directories (default `0755`).

## Example Playbook

```yaml
- hosts:
    - cluster_machines
    - standalone_machine
    - VMs
  become: true
  roles:
    - role: upload_extra_files
      vars:
        upload_extra_files_upload_files:
          - src: files/custom.conf
            dest: /etc/myapp/custom.conf
            owner: root
            group: root
            mode: "0644"
          - src: files/plugins.tar.gz
            dest: /opt/myapp/plugins
            extract: true
            dir_mode: "0755"
        upload_extra_files_commands_to_run_after_upload:
          - systemctl restart myapp
```
