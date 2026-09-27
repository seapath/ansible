# Delivering a container workload to SEAPATH

This is what a supplier hands over so that a SEAPATH cluster runs its
application as a container workload, deployed by the
`deploy_containers_cluster` role (see [README.md](README.md)).

## How SEAPATH runs a workload

* Pacemaker runs the workload on one hypervisor of the cluster at a time, and
  starts it on another one when that node fails or is put in maintenance.
* Everything the workload needs on a node comes with it when it starts there:
  its networks, its data volume, its CPU cores. The other nodes keep nothing
  of it.
* The site values (addresses, VLANs, interfaces) are written in the SEAPATH
  inventory, and Ansible renders them into the quadlets the supplier delivers.
* A substation has no container registry and often no Internet access. Nothing
  is pulled, and no tool of the supplier runs on site.

## What is delivered

A directory, or an archive of one:

```
<application>-<version>/
  README.md                  the application, for the people who run it
  values.yaml                the site values the quadlets use
  inventory-example.yaml     the cluster_containers entry, with example values
  images/
    <image>-<version>.tar    one per image
    SHA256SUMS
  quadlets/
    <name>.pod.j2            when there is more than one container
    <name>-<container>.container.j2
    <name>-<network>.network.j2
  files/                     the first content of the data volume
```

`<name>` is the workload name. The quadlet file names are fixed, since systemd
names the units after them: `<name>.pod` runs as `<name>-pod.service`, the unit
Pacemaker starts.

### Images

* One archive per image, loadable by `podman load -i` on Podman 5.4: the
  output of `podman save`, or an OCI archive that holds that single image.
* Each archive carries the name the quadlets use, `localhost/<image>:<version>`.
  A new version is a new tag.
* The quadlets reference the images by that name. No `podman pull`, no registry
  name, no `ExecStartPre=` that fetches an image. `Mount=type=image` of another
  delivered image works, since it is loaded on every node.

### Quadlets

Target Podman 5.4 (SEAPATH Debian 13), with systemd 257.

1. **No `[Install]` section**, in any file. Pacemaker starts the workload; a unit
   that starts itself at boot would run on every node. The role refuses such a
   quadlet.
2. **One unit to start.** Several containers go in a pod (`Pod=`), and they
   reach each other on the pod's loopback.
3. **Networks of their own.** No `Network=host`, and no name of a host
   interface, bridge port or address in a container. Each network is a
   `.network` quadlet the pod names, made on the node that runs it and removed
   when it stops:

   ```ini
   [Unit]
   StopWhenUnneeded=yes

   [Network]
   NetworkName=<name>-<network>
   Driver=macvlan
   Options=parent={{ container.<network>_parent }}

   [Service]
   # Podman 5.4 has no NetworkDeleteOnStop.
   ExecStop=/usr/bin/podman network rm --force <name>-<network>
   ```

   * Station bus (IP): a macvlan on the site's bridge, with the address and MAC
     fixed in the pod (`Network=<name>-sbus.network:ip=...,mac=...`). They move
     with the workload, so MMS clients keep reaching it.
   * Process bus (SV, GOOSE): a macvlan on an Open vSwitch port that the
     network unit creates in `ExecStartPre=` and deletes in `ExecStopPost=`,
     restricted to the VLANs the application may see (`trunks=`).
   * A check that an address is present on a host interface has no place:
     the address is in the pod.
4. **State on the data volume.** Everything the application writes and must
   keep (settings changed in operation, its HMI's state, secrets) is under
   `/mnt/rbd/<name>/`, mounted with `Volume=` into the containers. That
   directory is a Ceph RBD image: it follows the workload from node to node.
   No named volume, no other host directory. A directory the application needs
   and the delivery does not fill is created by the quadlet
   (`ExecStartPre=/usr/bin/mkdir -p /mnt/rbd/<name>/<dir>`).
5. **CPU cores are allocated, never written.** No `--cpuset-cpus`,
   `CPUAffinity=`, `Slice=` or core number in an environment variable. A
   container that needs isolated cores asks for them once it runs:

   ```ini
   [Service]
   ExecStartPost=seapath-container-pin %N <isolation> <scheduler> <priority>
   ExecStopPost=-seapath-container-unpin %N
   ```

   * `<isolation>`: `exclusive_logical` (one logical CPU) or
     `exclusive_physical` (a whole physical core).
   * `<scheduler> <priority>`: `FIFO 90` gives that policy to every thread of
     the container. `APP 0` leaves each thread with the policy the application
     gives it, for a real-time process next to threads that must stay in
     SCHED_OTHER; the container then needs `AddCapability=CAP_SYS_NICE` and
     `Ulimit=rtprio=<priority>`.
   * The container starts on the housekeeping cores and is moved to its
     isolated cores about a second later. An application that pins its own
     threads reads the cores it was given with `sched_getaffinity` and keeps
     re-reading them: SEAPATH may move a container to other isolated cores
     while it runs.
   * A container without real-time needs has no such line. `CPUQuota=` and
     `MemoryMax=` are welcome.
6. **Templates.** A file ending in `.j2` is rendered by Ansible, where each site
   value is `{{ container.<key> }}`. A Podman Go template in it is protected with
   `{% raw %}{{.State.Pid}}{% endraw %}`. A file without `.j2` is copied as it
   is.
7. `HealthCmd=`, `Restart=`, `RestartPreventExitStatus=`, `StopTimeout=`,
   `Ulimit=`, `AddCapability=` and `Environment=` are used as usual. Never
   `--privileged`.

### Data volume

`files/` holds the first content of `/mnt/rbd/<name>/`: configuration, SCL
files. SEAPATH copies it once, when it creates the volume, and never again: a
new version of the delivery leaves what the application wrote in operation
alone. A file the new version needs is created by the application when it is
missing, or by the quadlet.

### Configuration

A workload is configured in three places, one per kind of value:

| Kind | Examples | Where it is | How it changes |
|---|---|---|---|
| Fixed by the supplier | internal ports, interface names in the pod, real-time priority | written in the quadlets | a new version of the delivery |
| Proper to the site | addresses, MACs, VLANs, whether the clock is checked | `values.yaml` keys, rendered into `Environment=` lines and networks | the SEAPATH inventory, then a run and a restart of the workload |
| Set in operation | thresholds, SCL files, an HMI's state | the data volume, written by the application | by the application, through its HMI or MMS; kept by every redeployment |

An environment variable is read once, when the process starts: changing one
restarts the workload. So an environment variable carries what the
application needs to start (identity, addresses), and a value an operator
tunes in service belongs to the application's own configuration, on the data
volume, where it changes without a redeployment.

Secrets (passwords, tokens) are neither in the quadlets nor in `values.yaml`:
the application reads them from files under `/mnt/rbd/<name>/`, and the
delivery's README names those files.

### Site values

`values.yaml` lists every key the templates read as `{{ container.<key> }}`,
and nothing else. It is what an installer builds its form from and checks the
values against, so each key says what it is:

```yaml
sbus_ip:
  description: The address of the IED on the station bus, the one in the CID.
  format: ipv4
  example: 192.0.2.21
pb_vlans:
  description: The VLANs of the SV the IED reads and of the GOOSE it sends.
  format: vlan_list
  example: "100,300"
clock_synchronized:
  description: 1 once the PTP of the node is checked.
  format: integer
  min: 0
  max: 1
  default: 0
  example: 1
```

| Field | Required | Meaning |
|---|---|---|
| `description` | yes | One sentence, for the person filling it in |
| `format` | yes | `string`, `integer`, `boolean`, `ipv4`, `ipv4_network` (`192.0.2.0/24`), `mac`, `vlan_list` (`100,300`), `name` (an interface, bridge or port name, 15 characters at most) |
| `example` | yes | A valid value, the one `inventory-example.yaml` carries |
| `default` | no | The value used when the site gives none. A key without a default must be given |
| `min`, `max` | no | Bounds of an `integer` |

A new version of a delivery keeps the keys of the previous one. A key it adds
has a default, so that a site can take the new version with the values it
already has.

### Inventory example

The `cluster_containers` entry SEAPATH adds to its inventory, with a value for
every key of `values.yaml`. The paths are the delivery's own: whoever installs
it rewrites them to where the files end up. Where the workload runs
(`preferred_host`, `pinned_host`) is the site's choice, among nodes the
supplier does not know, and is not in the example.

```yaml
cluster_containers:
  <name>:
    unit: <name>-pod.service
    images:
      - name: localhost/<image>:<version>
        archive: ../inventories/<name>/<image>-<version>.tar
    quadlets:
      - ../inventories/<name>/<name>.pod.j2
      - ...
    rbd:
      size: 256M
      files:
        - { src: ../inventories/<name>/files/<file>, dest: <file> }
    sbus_ip: 192.0.2.30
    ...
```

## Checking a delivery before sending it

* `podman load -i` loads every archive and names each image as the quadlets
  do.
* Rendered with example values and placed in `/etc/containers/systemd/`, the
  quadlets pass Podman's generator: `/usr/libexec/podman/quadlet -dryrun`
  prints the units and no error.
* `grep -l '^\[Install\]' quadlets/*` prints nothing.
* The keys of `values.yaml` are exactly the `container.<key>` the templates
  read, apart from `container.images`, and each example is valid for its
  format.
* Started by hand on a machine with Podman 5.4 (`systemctl start
  <name>-pod.service`), the workload runs with an empty `/mnt/rbd/<name>/`
  filled from `files/`, stops cleanly, and leaves no network behind
  (`podman network ls`).
