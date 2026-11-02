# Configure Physical Machine Role

This role applies the SEAPATH prerequisites for any physical machine (hypervisor or observer).

## Requirements

No requirement.

## Role Variables

| Variable                       | Type        | Comments                                                                                                                             |
|--------------------------------|-------------|--------------------------------------------------------------------------------------------------------------------------------------|
| extra_sysctl_physical_machines | String      | Custom systctl configuration separate by new spaces                                                                                  |
| extra_kernel_modules           | String list | List of Kernel modules to load when booting                                                                                          |
| admin_user                     | String      | Administrator Unix username                                                                                                          |
| logstash_server_ip             | String      | Address IP of the logstash server                                                                                                    |
| pacemaker_shutdown_timeout     | String      | Custom timeout for stopping the systemd Pacemaker service. Time is a seconds, but support the min suffix to use minutes.Default 2min |
| chrony_wait_timeout_sec        | String      | Custom timeout for stopping the systemd Chrony service. Time is a seconds, but support the min suffix to use minutes.Default 180     |
| configure_physical_machine_distro_extra_modules | String list | List of distro specific kernel modules to load during boot |
| configure_physical_machine_initramfs | String | The initramfs tool used by the distribution. Can be `initramfs-tools` or `dracut`. Do not set if the initramfs shouldn't be configured. |

## RAID root on LVM (initramfs-tools)

Since lvm2 2.03.15 the udev rules only activate complete volume groups, so a root LV on RAID would not boot with a dead disk. The role installs the initramfs-tools script `local-block/lvm2`, which activates the incomplete VGs in degraded mode once 2/3 of the root delay (`max(30, rootdelay)` seconds) is spent and the root device is still missing. A healthy machine never reaches it.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.configure_physical_machine }
```
