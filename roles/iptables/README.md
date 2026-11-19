# Iptables Role

This role configures load iptables rules.

Rules should be defined in iptables-save/iptables-restore format.

Only IPv4 rules or supported.

## Requirements

No requirement.

## Role Variables

Rules can be defined in a file with `iptables_rules_path` or in an Ansible template with `iptables_rules_template_path`. Do not use both variables at the same time.

| Variable                     | Required | Type   | Default | Comments                                                                                                                        |
|------------------------------|----------|--------|---------|---------------------------------------------------------------------------------------------------------------------------------|
| iptables_rules_path          | no       | String |         | Path in the Ansible machine to a file containing IPv4 iptables rules in iptables-save/iptables-restore format                   |
| iptables_rules_template_path | no       | String |         | Path in the Ansible machine to an Ansible template file containing IPv4 iptables rules in iptables-save/iptables-restore format |
| iptables_backend             | no       | String | `auto`  | How the rules are applied: `auto`, `iptables` or `nftables`, see below                                                          |
| iptables_nftables_conf       | no       | String | `/etc/nftables.conf` | Ruleset written and loaded at boot by nftables.service in nftables mode                                            |
| iptables_register_essential_services | no | Bool | `true` | In nftables mode, declare nftables.service to the Cukinia tests                                                            |

## Backends

The rules are always deployed to `/etc/iptables/rules.v4`, which stays the
file to edit.

With `iptables`, the role loads them with `iptables-restore`, and
netfilter-persistent loads them at boot.

With `nftables` (Debian only), the role translates them with
`iptables-restore-translate` and writes the result to `/etc/nftables.conf`,
which it loads with `nft` and nftables.service loads at boot.
netfilter-persistent is disabled, and the role fails if a rule has no
nftables translation. Each table of the rules is deleted and created again on
every load, as `iptables-restore` does, and the tables of other tools
(libvirt, netavark) are left alone. `iptables -L` cannot read tables written
by nft: use `nft list ruleset`.

`auto`, the default, keeps `iptables`. It switches to `nftables` on a Debian
host where `iptables-restore --test` reports an extension that the running
kernel lacks: the Debian 7.x kernels no longer provide the xtables NAT
targets (MASQUERADE, SNAT, DNAT). When the rules load with `iptables-restore`
again, the role goes back to `iptables`.

## Example Playbook

```yaml
- name: Configure Iptables
  hosts: cluster_machines
  roles:
    - { role: seapath_ansible.iptables }
```
