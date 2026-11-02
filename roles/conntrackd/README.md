# Conntrackd Role

This role configure the conntrackd feature

## Requirements

No requirement.

## Role Variables

- conntrackd_ignore_ip_list

| Variable                   | Required | Type   | Default | Comments                                                |
|----------------------------|----------|--------|---------|---------------------------------------------------------|
| conntrackd_ignore_ip_list  | no       | Bool   | none    | Enable contrackd if the variable is defined             |
| conntrackd_interface       | no       | String | team0   | Set the network interface on which conntrackd will work |
| conntrackd_pacemaker_router | no      | String | ""      | Pacemaker resource of the router: run conntrackd as a promotable clone that follows it |

## Router failover with Pacemaker

By default conntrackd is a systemd service on every node, with its external
cache disabled: each node writes the sessions it receives into its own kernel
table. Nothing refreshes those copies, since conntrackd only sends a session
again when its TCP state changes. When a copy expires, its deletion is sent
back and removes the live session on the router, which loses its NAT and
resets the connection.

Set `conntrackd_pacemaker_router` to the resource the routed IPs and routes
are colocated with to use the active/backup model of conntrackd instead:

- the external cache is enabled, so the other nodes keep the sessions in
  conntrackd memory and their kernel table stays untouched;
- Pacemaker runs conntrackd as the promotable clone `cl_conntrackd`
  (`ocf:heartbeat:conntrackd`), whose promoted instance is colocated with the
  router. On promotion it commits its external cache into the kernel
  (`conntrackd -c`) and sends its table to the others. The promotion is
  ordered before the router starts when both happen in the same transition;
- `conntrackd.service` is disabled.

The clone is created once. A configuration change restarts it.

In both modes the role replaces `/etc/logrotate.d/conntrackd`: the Debian file
restarts conntrackd every week, at the same midnight on every node.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.conntrackd }
```

With the router held by the `V_PRD_MMS_POSTE` resource:

```yaml
conntrackd_pacemaker_router: V_PRD_MMS_POSTE
```
