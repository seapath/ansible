# vm_manager API Role

This role configures the vm_manager REST API feature.

## Requirements

No requirement.

## Role Variables

| Variable                   | Required | Type    | Comments                                                                                   |
|----------------------------|----------|---------|--------------------------------------------------------------------------------------------|
| vmmgr_http_tls_crt_path    | No       | String  | Path in the Ansible machine to the TLS certificate. If not set, it will be generated       |
| vmmgr_http_tls_key_path    | No       | String  | Path in the Ansible machine to the TLS private key. If not set, it will be generated       |
| vmmgr_http_local_auth_file | No       | String  | Optional path in the target to an existing basic HTTP auth file                            |
| vmmgr_http_port            | No       | Integer | Port to listen                                                                             |
| admin_cluster_ip           | No       | String  | IP address where connections will be listened                                              |
| vmmgr_http_api_acl         | No       | String  | Extra Nginx "server" configuration                                                         |
| enable_vmmgr_http_api      | No       | Bool    | Set to true to enable vm-manager REST API. Default is disable and the role will do nothing |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.vmmgrapi }
```
