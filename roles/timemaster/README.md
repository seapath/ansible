# Timemaster Role

This role configures timemaster

## Requirements

No requirement.

## Role Variables

| Variable                         | Required | Type    | Default | Comments                                                                                                                               |
|----------------------------------|----------|---------|---------|----------------------------------------------------------------------------------------------------------------------------------------|
| seapath_distro                   | yes      | String  |         | SEAPATH variant. CentOS, Debian or Yocto. The variable can be set automatically using the detect_seapath_distro role                   |
| ptp_interface                    | no       | String  |         | Network interface to use for PTP. The interface must support PTP hardware reception. If not set the PTP configuration will be skipped. |
| ptp_vlanid                       | no       | Integer |         | Optional VLAN ID to use with PTP                                                                                                       |
| ntp_servers                      | no       | String  |         | List of NTP/SNTP servers separated by a new line. If not set NTP configuration will be skipped                                         |
| timemaster_ptp_network_transport | no       | String  | "L2"    | PTP transport configuration. "L2" or "UDP"                                                                                             |
| timemaster_ptp_delay_mechanism   | no       | String  | "P2P"   | PTP delay mechanism. "P2P" or "E2E"                                                                                                    |
| timemaster_ptp_domain_number     | no       | Integer | 0       | PTP domain number. Value from 0 to 255                                                                                                      |
| timemaster_ptp_minor_version     | no       | Integer | 1       | PTP minor version. 0 or 1                                                                                                        |
| timemaster_ptp_custom_options    | no       | String  | null    | List of options to add to the ptp4l configuration section separated by a new line. Skipped if not set                                                                                                      |
| timemaster_ntp_poll              | no       | Integer | 6       | Poll interval of the NTP servers, as a power of two in seconds. See [NTP fallback](#ntp-fallback) |
| timemaster_ntp_samples           | no       | Integer | 10      | Number of samples chrony keeps for each NTP server. See [NTP fallback](#ntp-fallback) |
| timemaster_ptp_ntp_options       | no       | String  | null    | Extra options appended to the chrony refclock line of the PTP domain (timemaster `ntp_options`). Skipped if not set. See [NTP fallback](#ntp-fallback) |
| timemaster_chrony_custom_options | no       | List    | null    | Lines added to the generated chrony configuration, after the SEAPATH defaults. Skipped if not set. See [NTP fallback](#ntp-fallback) |




## NTP fallback

When the PTP source is lost, chrony stops receiving samples from phc2sys and
marks the refclock unreachable after 8 polls. It can still select it: an
unreachable source stays selectable as long as its newest sample is not older
than the oldest sample of the reachable sources. The NTP servers keep a fixed
number of samples at a fixed poll interval, so the switch to NTP happens about
`timemaster_ntp_samples` x 2^`timemaster_ntp_poll` seconds after the PTP loss:
10 x 64 s, about 11 minutes, by default.

During that holdover the system clock keeps the frequency learned under PTP,
which is usually more accurate than NTP for the first minutes. Pick the switch
delay from the holdover budget of the machine. For instance, the following
switches after about 2 minutes (8 x 16 s), at the cost of more NTP requests
and a noisier NTP estimate:

```yaml
timemaster_ntp_poll: 4
timemaster_ntp_samples: 8
```

chrony can also deselect the PTP source earlier, when its estimated error
grows above the one of the NTP servers. That error grows by `maxclockerror`
(1 ppm by default) per second of holdover. Global chrony directives can be
added with `timemaster_chrony_custom_options`, but they apply to every source
and to the error model of the local clock.

With chrony 4.8 or later, `maxunreach` bounds the number of polls an
unreachable source stays selected. The PTP refclock polls every second, so the
following switches to NTP about 8 + 60 seconds after the PTP loss:

```yaml
timemaster_ptp_ntp_options: "maxunreach 60"
```

Debian 13 ships chrony 4.6.1, which lacks `maxunreach`.

## Example Playbook

```yaml
- name: Configure Timemaster
  hosts: cluster_machines
  become: true
  vars:
    ptp_interface: "ens0"
    ptp_vlanid: 100
    ntp_servers: >-
      192.168.1.4
      192.168.1.8
  roles:
    - { role: seapath_ansible.timemaster }
```
