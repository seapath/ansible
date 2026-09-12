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
| `/usr/local/bin/seapath-rbd-mount` | Wait for the pool, then map the image and mount it at `/mnt/rbd/<image>`, creating and formatting it on first use. Called from `ExecStartPre=`. |
| `/usr/local/bin/seapath-rbd-unmount` | Unmount and unmap every mapping of the image. Called from `ExecStopPost=`. |

A quadlet using an RBD-backed volume declares two lines, and nothing in
`[Unit]`:

```ini
[Container]
Volume=/mnt/rbd/<image>:/<path-in-container>:rw

[Service]
ExecStartPre=/usr/local/bin/seapath-rbd-mount <image> [<size>]
ExecStopPost=/usr/local/bin/seapath-rbd-unmount <image>
```

`seapath-rbd-mount` carries the wait for Ceph itself: at boot the quorum forms
a minute or two after `network-online.target`, which is when the container unit
starts, so the mount would otherwise run against a cluster that is still
forming. The helper blocks until `rbd ls` answers on the pool, for at most
300 s, and sends `EXTEND_TIMEOUT_USEC` to systemd while it waits so that
`TimeoutStartSec` (90 s by default, and it covers `ExecStartPre=`) does not cut
the wait short. That notification needs `NotifyAccess=all`, which podman's
quadlet generator emits for every container unit, so a quadlet needs no
`TimeoutStartSec` of its own. Run outside such a unit the notification is
refused, the wait is capped by the caller's own timeout, and the helper logs it.

Should Ceph never answer, the helper exits after 300 s and the container fails.
`Restart=` then retries roughly every 300 s, which is far enough apart to stay
clear of `StartLimitBurst` (5 starts in 10 s by default), so the container
recovers on its own once the cluster is up.

The design and the alternatives that were measured are written up in
[ARCHITECTURE.md](ARCHITECTURE.md).
