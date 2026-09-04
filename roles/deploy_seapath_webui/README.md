<!--
Copyright (C) 2026 RTE
SPDX-License-Identifier: CC-BY-4.0
-->

# deploy_seapath_webui

Deploys the SEAPATH management web UI as a podman quadlet unit, on every
machine the inventory declares.

The service edits the inventory repository and runs these playbooks over SSH,
including against the machine it runs on. It configures no machine itself, so
this role is the only thing that writes to a host on its behalf: the quadlet,
the state directories, and the three Unix groups that grant each role.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `deploy_seapath_webui_enabled` | `true` | Deploy and start. False stops the service and removes the unit, keeping the state |
| `seapath_webui_image` | `docker.io/insatomcat/seapath-webui:latest` | Image reference. `latest` is the tag the ISO installs and preloads. Set it to an exact tag to pin a version, and editing it then applying is how the service is updated |
| `deploy_seapath_webui_bind_address` | `{{ ip_addr }}` | Listen address. `auto` resolves the interface carrying the default route, which is what a machine that has never converged boots with |
| `deploy_seapath_webui_port` | `8006` | Listen port |
| `deploy_seapath_webui_additional_sans` | `ip_addr`, `cluster_ip_addr` | Extra names in the self signed certificate |
| `deploy_seapath_webui_admin_group` | `seapath-admin` | Unix group granting the admin role, with the operator and viewer groups beside it |
| `deploy_seapath_webui_ansible_user` | `{{ ansible_user }}` | The account the trust targets. Its home is read with `getent` |
| `deploy_seapath_webui_state_dir` | `/etc/seapath/webui` | PKI, session secret, SSH keys |
| `deploy_seapath_webui_inventory_dir` | `/etc/seapath/inventory` | The inventory repository, which is the audit trail |
| `deploy_seapath_webui_data_dir` | `/var/lib/seapath-webui` | Run traces, artefacts, and a collection installed on the node |
| `deploy_seapath_webui_cpu_affinity` | computed from `isolcpus` | Housekeeping CPUs. Empty on a machine with no isolated CPU, and the container is left unpinned |
| `deploy_seapath_webui_restart_delay` | `30` | Seconds between the end of the play and the restart |

`seapath_webui_image` is the one variable without the role name as a prefix.
It is the one an inventory sets, and inventories already carry it under this
name.

## The restart is out of band, and that is the point

This role deploys the tool that ran it. On the machine serving the UI, the
container it replaces is the process recording the run: a `state: restarted`
handler would cut `ansible-runner` mid task, the SSH session would die, and the
run would have no result at all.

So the restart is handed to systemd as a transient timer with `systemd-run
--on-active`. The command returns at once, the play reaches its end, the run
writes its own result, and the container is replaced a few seconds later. What
an operator sees is a page that stops answering and comes back on the new
version.

A play that takes longer than `deploy_seapath_webui_restart_delay` to finish
still loses the end of its own run on that machine. The web UI reports such a
run as interrupted and says that is what applying this playbook looks like.

The image is pulled by a task rather than by that timer, so a registry the
machine cannot reach fails the run in front of the operator who asked for it. A
site that preloaded the image keeps it: nothing is pulled when the tag is
already present.

## What this role never does

It does not create the `ansible` account. That account comes from the SEAPATH
image carrying the site key, and the web UI appends its own key to its
`authorized_keys` in order to reach even this machine. A machine missing it was
not installed from a SEAPATH image, and inventing a home directory for a user
nobody created would be a second problem rather than a recovery.

It does not delete the state directories when disabled. They hold the trust
material and the inventory repository.
