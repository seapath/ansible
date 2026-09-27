# Delivering a container workload to SEAPATH

This is what a supplier hands over so that a SEAPATH cluster runs its
application as a container workload, deployed by the
`deploy_containers_cluster` role (see [README.md](README.md)).

## How SEAPATH runs a workload

* Pacemaker runs the workload on one hypervisor of the cluster at a time, and
  starts it on another one when that node fails or is put in maintenance.
* Everything the workload needs on a node comes with it when it starts there:
  its networks, its data volume, its CPU cores. Its configuration files,
  when it has any, are already on every node, written from the inventory by
  each deployment.
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
  checks.yaml                optional: values of the configuration files that repeat site values
  inventory-example.yaml     the cluster_containers entry, with example values
  images/
    <image>-<version>.tar    one per image
    SHA256SUMS
  quadlets/
    <name>.pod.j2            when there is more than one container
    <name>-<container>.container.j2
    <name>-<network>.network.j2
  examples/                  optional: an example of each configuration file
```

`<name>` is the workload name, the key of its `cluster_containers` entry. The
delivery proposes one, the key of `inventory-example.yaml`, and the site may
install it under another: a substation that runs the application twice, a
relay on each of two bays, installs the same delivery under two names. So
everything the workload makes on a node is named after the entry:

* The quadlet file names start with `<name>`, since systemd names the units
  after them: `<name>.pod` runs as `<name>-pod.service`, the unit Pacemaker
  starts. Installed under another name, the files are renamed, the proposed
  name replaced by the site's at the start of each.
* In the quadlets, the pod, the containers, the networks and the host
  directories are written with `{{ container.name }}`, which holds the
  workload name: `PodName={{ container.name }}`,
  `Pod={{ container.name }}.pod`, `ContainerName={{ container.name }}-<container>`.
  A quadlet that names the workload is a template, ending in `.j2`.
* What the workload makes on the host besides, such as the Open vSwitch port
  of a network, is named by a site value: two copies need two of them, and an
  interface name has 15 characters at most.

Inside a container, paths are the application's, the same whatever the
workload is called: `/etc/<application>`, `/var/lib/<application>`.

A delivery whose quadlets write the proposed name literally runs under that
name only.

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
   NetworkName={{ container.name }}-<network>
   Driver=macvlan
   Options=parent={{ container.<network>_parent }}

   [Service]
   # Podman 5.4 has no NetworkDeleteOnStop.
   ExecStop=/usr/bin/podman network rm --force {{ container.name }}-<network>
   ```

   * Station bus (IP): a macvlan on the site's bridge, with the address and MAC
     fixed in the pod
     (`Network={{ container.name }}-sbus.network:ip=...,mac=...`). They move
     with the workload, so MMS clients keep reaching it.
   * Process bus (SV, GOOSE): a macvlan on an Open vSwitch port that the
     network unit creates in `ExecStartPre=` and deletes in `ExecStopPost=`,
     restricted to the VLANs the application may see (`trunks=`). The port's
     name is a site value.
   * A check that an address is present on a host interface has no place:
     the address is in the pod.
4. **Two host directories, and no other.** The configuration of the site,
   read only, and the state the application writes, which follows the workload
   from node to node on a Ceph RBD image:

   ```ini
   Volume=/etc/seapath-containers/{{ container.name }}:/etc/<application>:ro
   Volume=/mnt/rbd/{{ container.name }}:/var/lib/<application>
   ```

   No named volume, no other host directory. A workload without configuration
   files has no first line, one that writes nothing to keep has no second.
   A directory the application needs under `/var/lib/<application>` is created
   by the application, or by the quadlet
   (`ExecStartPre=/usr/bin/mkdir -p /mnt/rbd/{{ container.name }}/<dir>`).
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
   value is `{{ container.<key> }}` and the workload name
   `{{ container.name }}`. A Podman Go template in it is protected with
   `{% raw %}{{.State.Pid}}{% endraw %}`. A file without `.j2` is copied as it
   is.
7. `HealthCmd=`, `Restart=`, `RestartPreventExitStatus=`, `StopTimeout=`,
   `Ulimit=`, `AddCapability=` and `Environment=` are used as usual. Never
   `--privileged`.

### Configuration files

Configuration files are optional. A workload whose configuration is made in
operation, through its own HMI, API or protocol (MMS), may keep all of it in
its state instead, on the RBD image (see "State"): it has no configuration
file, its delivery no `examples/` and no `checks.yaml`, and it starts empty on
an empty image. Its configuration then follows it from node to node, is kept by
the snapshots of the image, and is never deployed by SEAPATH; the application
offers its export and import. Configuration files suit a configuration made by
an engineering tool and deployed with the site values; the state suits one the
operators make on the workload itself. The rest of this section is for the
workloads that have configuration files.

The configuration files belong to the site: a CID produced by the system
configuration tool, base settings. The delivery gives an example of each in
`examples/`, with the example values of `values.yaml`. A file ending in `.j2`
is a template rendered with the site values, as a quadlet.

* At the first installation, the site starts from the examples and replaces
  them with its own. A new version of the delivery never replaces them.
* Each deployment writes them to `/etc/seapath-containers/<name>/` on every
  node, mounted read only on `/etc/<application>`. A change applies when the workload
  restarts.
* A new version that expects one more file gives an example of it and says so
  in its README. The site adds it before deploying: SEAPATH stops the
  deployment while it is missing, and never takes the example in its place.
* The application reads its configuration in `/etc/<application>` and never writes
  there.

### State

What the application writes in operation and must keep (settings changed by
MMS, an HMI's state, or its whole configuration when it has no configuration
file) goes to `/var/lib/<application>`, on the RBD image. SEAPATH creates the image
empty and never writes to it.

* Write it in a file that carries a format number, atomically: a temporary
  file, `fsync`, then a rename. SEAPATH snapshots the image while the workload
  runs, before each new version; the snapshot holds what a power cut would
  leave.
* With configuration files, store only what changed in operation, keyed by what the configuration names
  (the 61850 references of the CID): the site can then deliver a new CID and
  keep the settings changed in operation. A setting written in operation keeps the base value it replaced; when
  the configuration gives that setting another base value, the new one wins.
* A new version reads the state the previous one wrote, and migrates it forward
  when its format changes. The README of the delivery says so when it does.
* Starting the workload again from nothing puts the image aside and gives the
  workload an empty one: the application starts from its configuration files
  alone, or empty when it has none.

### Configuration

A workload is configured in three places, one per kind of value:

| Kind | Examples | Where it is | How it changes |
|---|---|---|---|
| Fixed by the supplier | internal ports, interface names in the pod, real-time priority | written in the quadlets | a new version of the delivery |
| Proper to the site | addresses, MACs, VLANs, whether the clock is checked | `values.yaml` keys, rendered into `Environment=` lines and networks | the SEAPATH inventory, then a run and a restart of the workload |
| Configuration of the site | CID, base settings | configuration files, in `/etc/<application>`; or, for a workload configured in operation, its state in `/var/lib/<application>` | the SEAPATH inventory, then a run and a restart of the workload; or the application |
| Set in operation | thresholds changed by MMS, an HMI's state | `/var/lib/<application>`, written by the application | by the application, through its HMI or MMS; kept by every redeployment |

An environment variable is read once, when the process starts: changing one
restarts the workload. So an environment variable carries what the
application needs to start (identity, addresses), and a value an operator
tunes in service belongs to the application's state, where it changes without
a redeployment.

Secrets (passwords, tokens) are neither in the quadlets, nor in `values.yaml`,
nor in the configuration files: the application reads them from files under
`/var/lib/<application>`, and the delivery's README names those files.

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

### Checks

A configuration file written by the site's own tool can repeat site values:
the CID holds the address of the IED and the VLANs of its GOOSE, which the
quadlets also get from `values.yaml`. When they differ, the workload starts
and its frames are dropped. `checks.yaml` lists these values, and SEAPATH
compares them before each deployment:

```yaml
- file: O61850PROT.cid
  xpath: "//scl:GSE/scl:Address/scl:P[@type='VLAN-ID']"
  namespaces: { scl: "http://www.iec.ch/61850/2003/SCL" }
  base: 16
  match: in_list
  value: pb_vlans
```

`file` names a configuration file, `xpath` the XML elements, `value` the key
of `values.yaml`. `match` is `equal` (the default) or `in_list`, for a key that
is a comma-separated list of integers; `base: 16` reads integers written in
hexadecimal. A file the site renders from a `.j2` gets its values from
`values.yaml` and is not checked.

### Inventory example

The `cluster_containers` entry SEAPATH adds to its inventory, with a value for
every key of `values.yaml`. The paths are the delivery's own: whoever installs
it rewrites them to where the files end up, and, installing it under another
name, the quadlets and the `unit` as well. Where the workload runs
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
    config:
      - ../inventories/<name>/site/<file>
    checks: [...]                # the content of checks.yaml
    rbd:
      size: 256M
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
  read, apart from `container.images` and `container.name`, and each example
  is valid for its format.
* Rendered with `container.name` set to another name, no quadlet holds the
  proposed one: `grep -l <name>` on the rendered files prints nothing, and the
  workload can be installed twice.
* Started by hand on a machine with Podman 5.4 (`systemctl start
  <name>-pod.service`), with `examples/`, if any, in
  `/etc/seapath-containers/<name>/` and an empty `/mnt/rbd/<name>/`, the
  workload runs, stops cleanly, and leaves
  no network behind (`podman network ls`).
* Started again with the state the previous version wrote, it reads it.
* The checks of `checks.yaml`, if any, pass on the examples with the example values.
