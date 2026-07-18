# cephadm_install Role

This role installs the cephadm binary, prerequisites (users, groups, sudo), pulls required container images, and starts the local Podman registry before the cephadm cluster is set up. Cluster provisioning is handled by the `cephadm` role.

## Ceph version detection

When `cephadm_release` is not set in the inventory, the role detects the version of the `quay.io/ceph/ceph` container image already present on the nodes (the SEAPATH Debian ISO pre-embeds it) and uses it as `cephadm_release` for the whole deployment. Setting `cephadm_release` in the inventory disables the detection entirely: the inventory is the place to pin a version, not to repair a broken default.

Detection rules:

- The versions are read from the tags of the local `quay.io/ceph/ceph` images (`podman image ls`). Other images, including the `localhost:5000/ceph` tags pushed by this role, are ignored.
- The deployment fails if a node holds several ceph image versions, or if two nodes hold different versions. The error message lists the version found on each node; fix the images or pin `cephadm_release` to resolve it.
- If some nodes hold an image and others none, the nodes without image adopt the detected version and pull it.
- If no image is found on any node (image pulled at deploy time), the default version below is used and a warning is printed.

The detected version is set as a host fact, so it also applies to the `cephadm` role (bootstrap, `--image` flags) in later plays of the same run.

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
