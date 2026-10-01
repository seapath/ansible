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
| `quadlets` | Yes | | Quadlet files on the Ansible machine, copied to `/etc/containers/systemd/`. A file ending in `.j2` is a template, written without that suffix. |
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
| `state` | No | `present` | `absent` removes the workload. |
| `remove_rbd` | No | `false` | With `state: absent`, also delete the RBD image. |

Any other key is a site value: templates see the whole workload as `container`,
so `ip: 192.0.2.30` is `{{ container.ip }}` in a quadlet template. A template
that holds a podman Go template, such as `{{.State.Pid}}`, protects it with
`{% raw %}`. A plain file is copied as it is.

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
| `deploy_containers_cluster_checks_fatal` | `false` | Whether a failed check stops the run, or only warns. |
| `deploy_containers_cluster_snapshots_kept` | `3` | Snapshots of its RBD image a workload keeps, and RBD images put aside by recreations. |
| `deploy_containers_cluster_restart` | `[]` | Workloads to restart at the end of this run, a name or a list (see below). Given with `-e`, never in the inventory. |
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
idempotence and removal. Ceph and Pacemaker are tested on a lab cluster.
