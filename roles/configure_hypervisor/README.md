# Configure Hypervisor Role

This role applies hypervisor specific configurations (virtualisation, realtime...).

## Requirements

No requirement.

## Role Variables

All variables are optional.

| Variable                  | Type         | Comments                                                                                                                                 |
|---------------------------|--------------|------------------------------------------------------------------------------------------------------------------------------------------|
| isolcpus                  | String       | CPU cores  isolate. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                                             |
| sriov_driver              | String       | Name of the module used for SR-IOV                                                                                                       |
| sriov                     | List of dict | List of network interfaces to configure for SR-IOV use. Dictionary list: `{ interface_name: number_of_interface_to_create }`             |
| cpusystem                 | String       | CPU cores reserved for system's processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                      |
| cpuuser                   | String       | CPU cores reserved for users' processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                        |
| cpumachines               | String       | CPU cores reserved for virtual machines processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10              |
| cpumachinesrt             | String       | CPU cores reserved for real-time virtual machines processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10    |
| cpumachinesnort           | String       | CPU cores reserved for no real-time virtual machines processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10 |
| cpuovs                    | String       | CPU cores reserved open vSwitch processes. Comma separated values, range can be defined using a dash: e.g. 4,6-7,10                      |
| custom_tuned_profile_path | String       | Path in the Ansible machine for custom tuned profile to be used                                                                          |
| configure_hypervisor_tuned_profiles_dir | String | Directory containing tuned profiles on the hypervisor. Defaults to /etc/tuned/profiles. |


## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_hypervisor }
```

## RBD volume helpers

On non-Yocto distributions the role installs the helpers used by quadlet
containers whose volumes live on Ceph RBD images (on Yocto the read-only root
filesystem gets them from the image itself, built in meta-seapath):

| File | Purpose |
|---|---|
| `/usr/local/bin/seapath-rbd-mount` | Map an image and mount it at `/mnt/rbd/<image>`, creating and formatting it on first use. Called from `ExecStartPre=`. |
| `/usr/local/bin/seapath-rbd-unmount` | Unmount and unmap every mapping of the image. Called from `ExecStopPost=`. |
| `/usr/local/bin/wait-for-rbd.sh` | Block until `rbd ls` answers on the pool, with a 300 s deadline. |
| `/etc/systemd/system/ceph-rbd-ready.service` | Readiness gate running the above. |

`ceph-rbd-ready.service` is installed but not enabled: it has no `[Install]`
section and is activated on demand by the units that depend on it, so it stays
inert on a hypervisor with no RBD-backed container. A quadlet declares:

```ini
[Unit]
After=ceph.target ceph-rbd-ready.service
Wants=ceph.target
Requires=ceph-rbd-ready.service

[Service]
ExecStartPre=/usr/local/bin/seapath-rbd-mount <image> [<size>]
ExecStopPost=/usr/local/bin/seapath-rbd-unmount <image>
```

`ceph.target` is wanted and not required because it does not exist on a node
running no local Ceph daemon, where requiring it would fail the start. Without
the gate, `seapath-rbd-mount` runs while the cluster is still forming its
quorum at boot and fails, and the retries allowed by `Restart=` exhaust
`StartLimitBurst` long before Ceph is up.
