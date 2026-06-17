# cephadm_install Role

This role installs the cephadm binary, prerequisites (users, groups, sudo), pulls required container images, and starts the local Podman registry before the cephadm cluster is set up. Cluster provisioning is handled by the `cephadm` role.

## Role Variables

| Variable                          | Required | Type    | Default                        | Comments                                                                                   |
|-----------------------------------|----------|---------|--------------------------------|--------------------------------------------------------------------------------------------|
| seapath_distro                    | No       | String  | Not set                        | SEAPATH distribution                                                                       |
| cephadm_install_release           | No       | String  | "20.2.0"                       | Version of the cephadm binary to download (fallback: `cephadm_release`)                    |
| cephadm_install_release_name      | No       | String  | "tentacle"                     | Name of the ceph release for repo install (fallback: `cephadm_release_name`)               |
| cephadm_install_downloadbinary    | No       | Boolean | false                          | Download cephadm to /tmp/cephadm (fallback: `cephadm_downloadbinary`)                      |
| cephadm_install_binary            | No       | Boolean | false                          | Copy cephadm from /tmp to /usr/local/bin (fallback: `cephadm_installbinary`)               |
| cephadm_install_repo              | No       | Boolean | false                          | Install cephadm repo with "cephadm add-repo" (fallback: `cephadm_installrepo`)             |
| cephadm_install_package           | No       | Boolean | false                          | Install cephadm with "cephadm install" (fallback: `cephadm_installpackage`)                |
| cephadm_install_common            | No       | Boolean | false                          | Install ceph-common with "cephadm install ceph-common" (fallback: `cephadm_installcommon`) |
| cephadm_install_pullimages        | No       | Boolean | false                          | Pull ceph container images and start local registry (fallback: `cephadm_pullimages`)       |
| cephadm_install_registryurl       | No       | String  | "docker.io/library/registry:2" | Name of the ceph release for repo install (fallback: `cephadm_release_name`)               |

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - detect_seapath_distro
    - cephadm_install
```
