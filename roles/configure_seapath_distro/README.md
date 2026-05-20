# Configure SEAPATH Distro Role

This role apply the basic SEAPATH prerequisites for any machine using a runtime package manager based SEAPATH distribution.

This role doesn't apply to SEAPATH Yocto distributions.

## Requirements

no requirement.

## Role Variables

| Variable             | Required | Type        | Comments                                                           |
|----------------------|----------|-------------|--------------------------------------------------------------------|
| admin_user           |  Yes     | String      | User to use for administration                                     |
| admin_passwd         |  No      | String      | Optional user password                                             |
| admin_ssh_keys       |  No      | String list | List of SSH public keys used to connect to the administration user |
| grub_append          |  No      | String list | List of extra kernel parameters                                    |
| apt_repo             |  No      | String list | List of apt repositories                                           |
| configure_seapath_distro_vim_config_dir |  Yes | String | VIM directory containing vimrc and vimrc.local      |
| configure_seapath_distro_grub_update_command  | Yes | String | Command to be run to update GRUB after configuration modification  |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_seapath_distro }
```
