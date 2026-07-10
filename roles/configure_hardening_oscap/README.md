# configure_hardening_oscap Role

This role runs an OpenSCAP XCCDF remediation after the main hardening has been applied. It must be run **after** `configure_hardening` (and `configure_hardening_physical_machine` where applicable) so that OpenSCAP can remediate any remaining non-compliant settings. `openscap` and `scap-security-guide` must be installed on the target host.

## Role Variables

| Variable                                 | Required | Type    | Default | Comments                                              |
|------------------------------------------|----------|---------|---------|-------------------------------------------------------|
| configure_hardening_oscap_ds_file        | Yes      | String  |         | Path to the SCAP data stream file on the target host  |
| configure_hardening_oscap_profile        | Yes      | String  |         | XCCDF profile ID to apply                             |
| configure_hardening_oscap_tailoring_file | No       | String  |         | Path to an optional XCCDF tailoring file on the host  |
| configure_hardening_oscap_apply_remediation | No    | Boolean | true    | Set to false to only run tests                        |
| configure_hardening_oscap_results_dir    | No       | String  | /tmp    | Directory where OpenSCAP result files are stored      |
| revert                                   | No       | Boolean | false   | When true, skip the remediation                       |

## Example Playbook

```yaml
- name: Run OpenSCAP remediation
  become: true
  hosts:
    - cluster_machines
    - standalone_machine
  roles:
    - configure_hardening_oscap
```
