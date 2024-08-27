# vm_manager API Role

This role configures the vm_manager http api feature

## Requirements

no requirement.

## Role Variables

- vmmgrapi_certs_dir
- vmmgr_http_tls_crt_path
- vmmgr_http_tls_key_path
- vmmgr_http_local_auth_file
- vmmgr_http_port
- vmmgr_http_api_acl
- vmmgr_http_local_auth_file

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.vmmgrapi }
```
