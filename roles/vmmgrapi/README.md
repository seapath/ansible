# vm_manager API Role

This role configures the vm_manager REST API feature.

The REST API must be protected by HTTP basic authentication. When
`enable_vmmgr_http_api` is true, `vmmgr_http_local_auth_file` is mandatory:
the role fails the play if it is not set or is empty. As a fallback, the
generated nginx configuration returns 403 instead of proxying requests when
no authentication file is configured.

## Requirements

No requirement.

## Role Variables

| Variable                   | Required            | Type    | Comments                                                                                   |
|----------------------------|---------------------|---------|--------------------------------------------------------------------------------------------|
| vmmgr_http_tls_crt_path    | No                  | String  | Path in the Ansible machine to the TLS certificate. If not set, it will be generated       |
| vmmgr_http_tls_key_path    | No                  | String  | Path in the Ansible machine to the TLS private key. If not set, it will be generated       |
| vmmgr_http_local_auth_file | Yes, if API enabled | String  | Path in the target to an htpasswd file used for HTTP basic authentication. Required when `enable_vmmgr_http_api` is true |
| vmmgr_http_port            | No                  | Integer | Port to listen                                                                             |
| vmmgr_http_api_acl         | No                  | String  | Extra Nginx server-block configuration (e.g. IP allow/deny ACLs). Does not replace authentication |
| enable_vmmgr_http_api      | No                  | Bool    | Set to true to enable vm-manager REST API. Default is disabled and the role will do nothing |
| vmmgrapi_ipaddress         | No                  | String  | IP address where connections will be listened                                              |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.vmmgrapi }
```
