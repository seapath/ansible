# Deploy containers on cluster role

This role deploys container workloads in a SEAPATH cluster, the way
`deploy_vms_cluster` deploys VMs. A workload is one or more images, the
quadlets that run them, the configuration files of the site, optionally a Ceph
RBD image for the state the workload writes and that must follow it from node
to node, and a Pacemaker resource that starts it on one node.

The role does not read the quadlets. It puts the images, the quadlets and the
configuration on every hypervisor of the cluster, creates the RBD image,
snapshots it when the images change, and creates the Pacemaker resource. CPU pinning, networks and gratuitous ARP stay
in the quadlets.

It is run by `playbooks/deploy_containers_cluster.yaml`.

What a supplier hands over for this role, and the rules its quadlets follow, is
in [DELIVERY.md](DELIVERY.md).

## Requirements

* A cluster set up by `cluster_setup_cephadm.yaml` and `cluster_setup_ha.yaml`.
* `seapath-rbd-mount` and `seapath-rbd-unmount`, installed by
  `configure_hypervisor` (see its README, section "RBD volume helpers"), for
  the workloads with an RBD image.
* The `lxml` Python module on the Ansible machine, for the workloads that
  declare `checks`.

## Inventory

The workloads are declared in `cluster_containers`, a mapping keyed by the
workload name, usually in the vars of `cluster_machines`. A workload is not an
inventory host: Ansible never connects to it.

| Key | Required | Default | Description |
|---|---|---|---|
| `quadlets` | Yes | | Quadlet files on the Ansible machine, copied to `/etc/containers/systemd/`. A file ending in `.j2` is a template, written without that suffix. Their names are the workload's own, `<name>.pod` or `<name>-<container>.container`: two workloads never write the same one. |
| `images` | No | `[]` | List of `name` and optional `archive`. Without `archive` the nodes pull `name`. With it, `archive` is a `podman save` file on the Ansible machine, loaded on every node: nothing is downloaded. |
| `unit` | No | `<name>.service` | The unit Pacemaker starts. For a pod `foo.pod` it is `foo-pod.service`. |
| `config` | No | `[]` | Configuration files on the Ansible machine, written to `/etc/seapath-containers/<name>/` on every node. A file ending in `.j2` is a template, written without that suffix. See "Configuration". |
| `checks` | No | `[]` | Values of the `config` files compared with site values before the run changes anything. See "Checks". |
| `rbd` | No | | `size` (required). `files`, a list of `src` and `dest` copied once when the image is created, is still read for the workloads that have it; `config` replaces it. |
| `preferred_host` | No | | Node the workload runs on when it is up, written as the constraint `seapath-preferred-<name>` with an infinite score, as `vm_manager` does for a VM. |
| `pinned_host` | No | | Node the workload runs on, and only there: `pin-<name>`. |
| `colocated_with` | No | `[]` | Pacemaker resources (VMs or workloads) to run on the same node. |
| `strong_colocation` | No | `false` | Make the colocations mandatory. |
| `monitor_interval`, `start_timeout`, `stop_timeout` | No | `10s`, `360s`, `100s` | Pacemaker operations. The start timeout covers the wait for Ceph of `seapath-rbd-mount` (300 s at most). |
| `update_steps` | No | `[]` | How the workload is updated while it runs. See "Updating a running workload". |
| `state` | No | `present` | `absent` removes the workload. |
| `remove_rbd` | No | `false` | With `state: absent`, also delete the RBD image. |

Any other key is a site value: templates see the whole workload as `container`,
so `ip: 192.0.2.30` is `{{ container.ip }}` in a quadlet template. A template
that holds a podman Go template, such as `{{.State.Pid}}`, protects it with
`{% raw %}`. A plain file is copied as it is.

`{{ container.name }}` is the workload name, the key of the entry, and no site
value takes that key. A template that names what the workload makes on a node
with it (its pod, its containers, its networks, the directories it mounts) can
be declared twice under two names, each entry listing its own copy of the
quadlets, renamed after it.

Paths to files on the Ansible machine are resolved against the playbook
directory, as for any role: `../inventories/foo.container` is found next to the
inventory when the inventory repository sits beside `playbooks/`.

Role variables:

| Variable | Default | Description |
|---|---|---|
| `deploy_containers_cluster_containers` | `cluster_containers` | The workloads. |
| `deploy_containers_cluster_archive_dir` | `/var/lib/seapath/containers` | Where the image archives are kept on the nodes. |
| `deploy_containers_cluster_written_dir` | `/var/lib/seapath/containers/quadlets` | Where each node records the quadlets it wrote for each workload. |
| `deploy_containers_cluster_config_dir` | `/etc/seapath-containers` | Where each node keeps the configuration of each workload. |
| `deploy_containers_cluster_started_dir` | `/run/seapath-containers` | Where a workload with `update_steps` notes, as it starts, the quadlets no step replaces. |
| `deploy_containers_cluster_checks_fatal` | `false` | Whether a failed check stops the run, or only warns. |
| `deploy_containers_cluster_snapshots_kept` | `3` | Snapshots of its RBD image a workload keeps, and RBD images put aside by recreations. |
| `deploy_containers_cluster_only` | `[]` | Workloads this run is limited to, a name or a list, every workload when empty (see below). Given with `-e`, never in the inventory. |
| `deploy_containers_cluster_restart` | `[]` | Workloads to restart at the end of this run, a name or a list (see below). Given with `-e`, never in the inventory. |
| `deploy_containers_cluster_update` | `[]` | Workloads this run updates while they run, a name or a list (see below). Given with `-e`, never in the inventory. |
| `deploy_containers_cluster_recreate` | `[]` | Workloads to start again from nothing in this run, a name or a list (see below). Given with `-e`, never in the inventory. |
| `deploy_containers_cluster_monitor_interval` | `10s` | Default monitor interval. |
| `deploy_containers_cluster_monitor_timeout` | `100s` | Monitor timeout. |
| `deploy_containers_cluster_start_timeout` | `360s` | Default start timeout. |
| `deploy_containers_cluster_stop_timeout` | `100s` | Default stop timeout. |

### A single container: nginx

```yaml
cluster_machines:
  vars:
    cluster_containers:
      nginxquadlet:
        images:
          - name: public.ecr.aws/nginx/nginx:1.31.5
        quadlets:
          - ../inventories/nginxquadlet.container.j2
          - ../inventories/nginxquadlet.network.j2
        rbd:
          size: 1G
        ip: 192.0.2.13
        mac: "02:42:ac:11:0f:03"
        parent: br0
        subnet: 192.0.2.0/24
        gateway: 192.0.2.1
```

`nginxquadlet.container.j2`:

```ini
[Unit]
Description=Nginx container with Ceph RBD volume

[Container]
Image={{ container.images[0].name }}
Volume=/mnt/rbd/nginxquadlet/html:/usr/share/nginx/html:Z
Volume=/mnt/rbd/nginxquadlet/logs:/var/log/nginx:Z
Network=nginxquadlet.network:ip={{ container.ip }},mac={{ container.mac }}

[Service]
Restart=on-failure
ExecStartPre=mkdir -p /mnt/rbd/nginxquadlet/html /mnt/rbd/nginxquadlet/logs
ExecStartPost=/bin/sh -c 'sleep 2; nsenter -t $(podman inspect -f "{% raw %}{{.State.Pid}}{% endraw %}" systemd-nginxquadlet) -n arping -q -c 1 -U -I eth0 {{ container.ip }}; exit 0'
```

`nginxquadlet.network.j2`:

```ini
[Unit]
Description=nginxquadlet network
StopWhenUnneeded=yes

[Network]
NetworkName=nginxquadlet
Driver=macvlan
Options=parent={{ container.parent }}
Subnet={{ container.subnet }}
Gateway={{ container.gateway }}

[Service]
# podman 5.4 has no NetworkDeleteOnStop.
ExecStop=/usr/bin/podman network rm --force nginxquadlet
```

### A pod: a protection relay

Two containers in a pod, two networks, one of them on an Open vSwitch port of
its own, its whole configuration (the bays, their settings, the CID generated
from them) on the RBD image, made through its HMI and MMS, and an image
delivered as an archive because the substation has no registry. A workload
whose configuration comes from an engineering tool lists its files under
`config` instead (see "Configuration"):

```yaml
      open61850-protect:
        unit: open61850-protect-pod.service
        images:
          - name: localhost/open61850-protect:1.0
            archive: ../inventories/open61850-protect-1.0.tar
        quadlets:
          - ../inventories/open61850-protect.pod.j2
          - ../inventories/open61850-protect-pb.network.j2
          - ../inventories/open61850-protect-sbus.network.j2
          - ../inventories/open61850-protect-rt.container
          - ../inventories/open61850-protect-shell.container.j2
        rbd:
          size: 128M
        preferred_host: node3
        pb_bridge: processbus
        pb_vlans: "100,300"
        pb_mac: "02:61:85:00:00:01"
        sbus_parent: eth2
        sbus_subnet: 192.0.2.0/24
        sbus_gateway: 192.0.2.1
        sbus_ip: 192.0.2.30
        sbus_mac: "02:61:85:00:00:02"
```

The process bus network makes its own OVS port, which `setup_ovs` does not
know about and would drop at boot:

```ini
[Unit]
StopWhenUnneeded=yes
After=openvswitch-switch.service seapath-config_ovs.service

[Network]
NetworkName=open61850-protect-pb
Driver=macvlan
Options=parent=o61850pb
IPAMDriver=none

[Service]
ExecStartPre=/usr/bin/ovs-vsctl --may-exist add-port {{ container.pb_bridge }} o61850pb -- set Port o61850pb vlan_mode=trunk trunks={{ container.pb_vlans }} -- set Interface o61850pb type=internal
ExecStartPre=/usr/bin/ip link set o61850pb up
ExecStop=/usr/bin/podman network rm --force open61850-protect-pb
ExecStopPost=/usr/bin/ovs-vsctl --if-exists del-port {{ container.pb_bridge }} o61850pb
```

The containers mount the RBD image, where the relay keeps its configuration
and what it records:

```ini
Volume=/mnt/rbd/open61850-protect:/var/lib/open61850-protect
```

A workload with configuration files mounts them read only as well:

```ini
Volume=/etc/seapath-containers/<name>:/etc/<name>:ro
```

The real-time container is pinned by `seapath-container-pin` in its own
quadlet, as without this role (see `roles/seapath_alloc`).

## Configuration

A workload may have no configuration file and keep all of its configuration on
its RBD image, made through its own HMI or protocol (see DELIVERY.md): its
entry has no `config`, and the role writes nothing to
`/etc/seapath-containers/<name>/`.

The configuration files of a workload belong to the site: a CID produced by
the system configuration tool, base settings. They sit in the inventory, next
to the entry, and a new version of the delivery never replaces them.

Every run writes them to `/etc/seapath-containers/<name>/` on every node, the
templates rendered with the entry, and removes from that directory what the
entry no longer lists. The quadlets mount it read only, so the node Pacemaker
starts the workload on already has it, and a change applies when the workload
restarts, as for a quadlet: the role says so and never restarts it. A node that
was unreachable during the run keeps the previous configuration until the next
run, as it keeps the previous quadlets.

A file the entry lists and the inventory lacks stops the run before any node
changes. A delivery gives an example of each configuration file it expects;
the run never takes the example in the site's place.

## Checks

A configuration file can repeat values the inventory also holds: the address
of the IED and the VLANs of its GOOSE are in the CID and in the site values.
A check compares them, on the Ansible machine, before any node changes:

| Key | Required | Description |
|---|---|---|
| `file` | Yes | The name of a `config` file, as written on the nodes. A template is rendered from the site values and is not checked. |
| `xpath` | Yes | The XML elements whose text is compared. |
| `namespaces` | No | Prefixes the XPath uses. |
| `value` | Yes | The site value, a key of the entry. |
| `match` | No | `equal` (default): every element holds the site value. `in_list`: every element holds one of the integers of a comma-separated site value. |
| `base` | No | The base the elements write their integers in: `16` for the VLAN-ID of a CID. |

A check that fails, or whose XPath finds nothing, is reported in red and the
run goes on. With `deploy_containers_cluster_checks_fatal: true` it stops the
run.

## How a workload runs

Pacemaker starts the unit on one node. What the unit needs comes with it
through systemd dependencies, on that node only:

* The networks: quadlet makes a container or a pod require the `.network`
  units it names. `StopWhenUnneeded=yes` and `ExecStop=podman network rm`
  remove the network when the workload stops, so the other nodes keep none.
* The RBD image: the role adds a drop-in to the unit,
  `/etc/systemd/system/<unit>.d/seapath-rbd.conf`, which requires
  `seapath-rbd@<name>.service`. That unit maps and mounts `rbd/<name>` at
  `/mnt/rbd/<name>`, and unmounts and unmaps it once the workload has stopped.
  The quadlets only name the mountpoint in their `Volume=`.

* What an update needs: for a workload with `update_steps`, a second
  drop-in, `seapath-handover.conf` (see "Updating a running workload").

The mount is a unit of its own because `seapath-rbd-mount` waits up to 300 s
for Ceph at cluster boot, and extends the start timeout while it waits with
`EXTEND_TIMEOUT_USEC`. systemd accepts that notification only from a unit with
`NotifyAccess=all`, which the units quadlet generates for pods do not have: in
the pod unit the wait would be cut at 90 s.

No quadlet may have an `[Install]` section, which would start the workload at
boot on every node, behind Pacemaker's back: the role refuses them.

## Deploying again

The role changes nothing that is up to date. A new quadlet or drop-in is
written on every node, but a running workload is never restarted: the change
applies the next time Pacemaker starts it, and the role says so. To apply it
now: `crm resource restart <name>`. Give images a fixed tag: a tag already
present on a node is not pulled again.

A new version of a workload is a new tag. The run removes from every node the
other tags of the same image that no declared workload uses, and every image
archive no workload declares any more. A version still used by a container,
the workload not restarted yet, stays until the next run after the restart.

The RBD image belongs to the workload: a new deployment never writes to it, so
what the workload wrote there (settings changed in operation) is kept. The
images a workload was deployed with are recorded in the metadata of its RBD
image (`seapath.images`). When they change, the role first takes a snapshot,
`rbd/<name>@<date>-<version left>`, and keeps the newest
`deploy_containers_cluster_snapshots_kept`. The workload runs meanwhile, so the
snapshot holds what a power cut would leave: an application that writes its
state atomically reads it back. To go back to a version, revert the inventory
commit, stop the workload, `rbd snap rollback` to the snapshot, run the playbook
and start the workload.

The definition of the workload is recorded there too, `seapath.definition`: a
JSON object of `format` (1), `name`, `entry`, the entry as the inventory
declares it, and `files`, in base64 and keyed by their path from the playbook
directory: each quadlet, `config` and `rbd.files` source, and every file of
the folder a delivery is installed from, `../inventories/<name>/` (its
`values.yaml`, `checks.yaml`, README, examples and site files), image
archives apart. They are read byte for byte on the Ansible machine. It is written again when
it changes, through `seapath-rbd-meta`, which reads the value from standard
input. A VM carries its XML on its disk the same way: the image and its
metadata are enough to put the workload back anywhere.

The RBD image is backed up with the guests by `backup_restore`, which
recognises it by `seapath.images`, leaves these snapshots alone, exports its
metadata and saves the container images (see its README, section "Container
workloads").

A workload that still has `rbd.files` gets them copied once, when the role
creates the image. If that fails, the role removes the half-filled image, so
the next run starts over.

A quadlet a new version renames or drops is removed from every node: each node
records in `deploy_containers_cluster_written_dir` the quadlets it wrote for a
workload, and removes the ones the entry no longer lists. A unit still running
from such a quadlet stops with the workload.

The Pacemaker resource is created with its constraints. Once it exists, its
operations and colocations are left as they are, and its placement follows the
entry: `seapath-preferred-<name>` and `pin-<name>` are written again when
`preferred_host` or `pinned_host` changed, and deleted when the entry no longer
has them. Pacemaker then moves a running workload to the node they name, which
is a stop and a start. The resource is banned from the cluster members that
are not hypervisors, the observers.

## Limiting a run to some workloads

```sh
ansible-playbook playbooks/deploy_containers_cluster.yaml \
  -e deploy_containers_cluster_only=open61850-protect
```

A run goes through every workload of `cluster_containers`, which on a cluster
that holds many takes long for a change to one. A run given
`deploy_containers_cluster_only` deploys, or removes when they are marked
`state: absent`, the workloads it names, and leaves every other one as it is:
its images, quadlets, configuration, RBD image and resource are neither checked
nor written. What a node keeps is still read from every workload declared, so
the images and archives of the others stay. A name `cluster_containers` does
not declare stops the run, and so does a workload named in
`deploy_containers_cluster_restart`, `deploy_containers_cluster_update` or
`deploy_containers_cluster_recreate` that the run leaves out. The variable is
for one run: written in the inventory, no run would reach the other workloads.

## Applying a change now

```sh
ansible-playbook playbooks/deploy_containers_cluster.yaml \
  -e deploy_containers_cluster_restart=open61850-protect
```

Once every node has the new images, quadlets and configuration, the run
restarts the workloads it names (`crm --wait resource restart`), so that a new
version, configuration or site value applies at once. A workload whose
resource the run created or recreated has just started and is not restarted
again. The variable is for one run: written in the inventory, every run would
restart the workload.

## Updating a running workload

```sh
ansible-playbook playbooks/deploy_containers_cluster.yaml \
  -e deploy_containers_cluster_update=open61850-protect
```

A restart stops the whole workload and starts it again, several seconds
without any of its services. A workload whose entry has `update_steps` is
updated while it runs: whatever the new version changes, a container handed
over is heard throughout, and the rest of the workload is interrupted for as
little as that version allows.

```yaml
      open61850-protect:
        ...
        update_steps:
          - handover: open61850-protect-rt.container
            network: open61850-protect-pb.network
            bridge: pb_bridge
            port: pb_port
            settle: update_settle
          - restart: open61850-protect-shell.service
```

| Step | For | What it gets |
|---|---|---|
| `handover` | A container whose only effect is what it sends on a network: two versions can run side by side as long as one is heard. | A stand-in on the new version keeps its service while the workload is updated. Neither two emitters nor a silence. |
| `restart` | A container that holds what two versions cannot share: a volume it writes, an address it listens on. | It is restarted alone when nothing but containers changed. |

Once every node has the new images and quadlets, on the node the workload
runs on:

1. The resource is put in maintenance (`crm resource maintenance <name>
   on`): Pacemaker neither monitors it nor acts on it.
2. The stand-in of each container handed over starts, on the new version,
   and takes its service.
3. The workload is brought to the new version:
   * the delivery changed nothing but the containers the steps name: each of
     them is restarted alone (`systemctl restart`), in the order of the
     steps, and the pod stays;
   * it changed the pod, a network or a container no step names: the unit of
     the workload is restarted, with all it makes.
4. Each container handed over takes its service back and its stand-in stops.
5. The resource is given back to Pacemaker, which finds it running.

A workload that runs nowhere is left alone: it starts with what was deployed.

Pacemaker is kept out because it would take a stop of step 3 for a failure,
and because a workload it started on another node would be heard beside the
stand-in of this one. Maintenance rather than `is-managed=false`: unmanaged,
the resource is still monitored, and the stops Pacemaker noted would have it
recover the resource, with a restart, once it manages it again.

When a stand-in does not start, nothing was touched: the resource is given
back to Pacemaker and the run fails. When the run fails later, with a
stand-in heard, it stops there and leaves the resource in maintenance: the
stand-ins keep their service, alone, and Pacemaker starts nothing. The run
says so. Run again once the cause is fixed, or the previous version deployed
again, the update finishes from where it is: it starts the workload, has its
containers heard and gives the resource back.

### Handover

The step names the quadlet of the container (`handover`), a container of the
pod, the quadlet of the network of the pod it sends on (`network`), and the
site values of the entry that hold the Open vSwitch bridge and the port that
network makes (`bridge`, `port`): the keys, as a check names its `value`,
so that the steps are the same on every site and a delivery carries them.
`settle` is the settle time: seconds (0 by default), or the site value that
holds them, for a time that depends on how the site sets the application.
The delivery is otherwise the one of any workload: nothing in its quadlets
is written for the handover. The role makes the stand-in from these two quadlets:

* `<container>-b.container`, the same container out of the pod, on
  `<network>-b.network` with the options the pod gives that network;
* `<network>-b.network`, the same network on a port of its own, `<port>b`.

The stand-in has a network namespace of its own, so the same interface, the
same MAC and the same command line as the container, and nothing of the pod
to clash with. It depends on nothing of the workload but its RBD image, which
it keeps mounted, so the workload can be restarted under it. It runs during
an update only.

Both ports receive. The bridge drops what comes from the port that is not in
service. `seapath-container-handover`, which the role installs on every node:

* `enter` starts the stand-in, whose port is made and closed before its
  container starts, waits for its unit to be active, then for the settle
  time, the time the application needs before its output can be trusted,
  and opens that port and closes the container's in one OpenFlow bundle;
* `leave` waits for the container to have run for `settle` seconds, swaps the
  ports back in one bundle and stops the stand-in.

A stand-in that does not start, or stops while settling, is stopped. A
container that does not come back leaves its stand-in in service.

The stand-in is alone: the other containers of the pod are out of its reach,
and it is out of theirs. The container must therefore do its duty without
them for as long as it stands in, and read what it needs from what it mounts.

The role adds a drop-in to the unit of the workload,
`/etc/systemd/system/<unit>.d/seapath-handover.conf`. As the unit starts, the
port of each container handed over, just made, is closed if its stand-in is
heard and open otherwise; once it has stopped, the rules are deleted. The
unit also notes, under `/run/seapath-containers/`, the checksums of the
quadlets no step replaces, which is how an update tells what the delivery
changed.

What the bridge guarantees is that one of the two is heard at any time. It
does not look into the frames: two versions that answer the same input at
different speeds may have a frame heard twice, or not at all, when the
switch falls between their two answers. On a lab cluster, with a protection
relay sending its trip by GOOSE and a fault every second, 51 833 switches
between a container and one made 0.2 to 0.9 ms slower lost no change of
state out of 1 800: 35 were heard at the first repetition, 4 ms later, and
28 from both. Between two of the same speed, 34 460 switches delayed none
out of 1 200. A sequence number the application keeps, such as the stNum of
a GOOSE, restarts at each of the two switches, as it does on a restart.

That relay, its delivery unchanged (a pod of its real-time container and its
IED shell), its resource started by Pacemaker, updated four times by these
tasks with a fault every second: 800 changes of state all heard on time,
eight changes of emitter and no moment with two. When only the containers
changed, the shell did not answer for 0.7 s; when a network of the pod
changed and the workload was restarted, for 1.9 to 3.3 s, the trip still
published throughout. An update whose pod could not start again left the
shell down for the minute it took to deploy a pod that could and to run the
update again: 420 changes of state all heard, from the stand-in then from
the container.

### Restart

`systemctl restart` of the unit the step names, while the pod and its other
containers stay. Quadlet has a pod stop with its last container, which a pod
of one container would do in the middle of that restart: in the pod quadlet
of a workload with `update_steps`, the role sets
`PodmanArgs=--exit-policy=continue`.

### Limits

* A workload started before it had `update_steps` is updated this way from
  its first update on, by the heavier way: its unit noted nothing as it
  started, so the workload is restarted as a whole, under its stand-ins. On
  the lab cluster, the relay deployed without steps then updated with them:
  420 changes of state all heard, its shell silent for 3.2 s.
* The stand-in needs the same resources as the container while both run: for
  a container pinned by `seapath-container-pin`, an isolated core that is
  free. Without one it does not start and the update fails before it touches
  the workload.
* The unit Pacemaker starts must stay while the containers change: it is a
  pod, never the container handed over.
* A handover is two switches, and an update lasts at least twice the settle
  time.
* During an update, two to three minutes with a settle time of a minute,
  and for as long as an update that failed is left unfinished, the resource
  is in maintenance: Pacemaker does not start the workload on another node
  if this one fails. An update is run by someone who watches it.

## Starting a workload again from nothing

```sh
ansible-playbook playbooks/deploy_containers_cluster.yaml \
  -e deploy_containers_cluster_recreate=nginxquadlet
```

The run stops the workload, deletes its Pacemaker resource, and puts its RBD
image aside as `rbd/<name>.<date>-<version left>`, with its snapshots. It then
deploys the workload as on a first deployment: a new empty RBD image, a new
resource, started. The configuration of the site is untouched; the state the
workload wrote is on the image put aside, of which the role keeps the newest
`deploy_containers_cluster_snapshots_kept`. The variable is for one run:
written in the inventory, every run would put the state aside again.

## Removing a workload

Set `state: absent` and run the playbook. The role stops the resource and
deletes it with its constraints, removes the quadlets, the drop-in, the
configuration and the image archives from every node, and the images no other
declared workload uses. The RBD image is deleted only with `remove_rbd: true`,
with its snapshots and the images put aside. The entry can then be deleted
from the inventory.

## Tests

The molecule scenario covers the node side: quadlet templates and plain files,
the configuration, the image loaded from an archive, the RBD drop-in, a quadlet
and a configuration file a new version drops, the refusal of `[Install]`,
idempotence and removal. Ceph, Pacemaker and the update of a running workload
(the stand-in, the drop-in, the handover on Open vSwitch, the restart of one
container and of the workload) are tested on a lab cluster; `tests/test_seapath_container_handover.py` covers
the handover tool.
