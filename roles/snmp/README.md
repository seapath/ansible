# SNMP Role

This role configure the SNMP feature

This role is disable SNMP if the *snmp_admin_ip_addr* variable is not defined.

## Requirements

No requirement.

## Role Variables

| Variable               | Required | Type         | Comments                                                                                                                              |
|------------------------|----------|--------------|---------------------------------------------------------------------------------------------------------------------------------------|
| seapath_distro         | yes      | String       | SEAPATH variant. CentOS, Debian or Yocto. The variable can be set automatically using the detect_seapath_distro role                  |
| snmp_accounts          | no       | List of dict | List of snmp_accounts, used for snmp v3. See below.                                                                                   |
| snmp_admin_ip_addr     | yes      | string       | SNMP agent IP address. If not set the role will disable SNMP.                                                                         |
| extra_snmpd_directives | no       | string       | Extra snmpd.conf configuration. If defined with snmp_accounts (v3), it becomes the whole snmpd configuration (the v2 conf is disabled)|

The *snmp_accounts* is a dictionary with the following members:

| *snmp_accounts* member | Required | Type   | Comments                     |
|------------------------|----------|--------|------------------------------|
| name                   | yes      | string | Name of the SNMP account     |
| password               | yes      | string | Password of the SNMP account |

The existence of the snmp_accounts is what enables snmp v3.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.snmp }
```
