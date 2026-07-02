# RFC: dynamic allocation of isolated CPU cores

## 1. Context

On a SEAPATH node, real time is the product. Some logical cores are removed from the Linux scheduler at boot (`isolcpus=`) and reserved for latency sensitive work; everything else (OS, daemons, Ansible, Ceph, Cockpit, ...) runs on the remaining *housekeeping* cores.

Four kinds of actors compete for that isolated pool, each configured by an unrelated mechanism that knows nothing about the other three:

| Actor | Configured by |
|---|---|
| VMs (vCPU, emulator, vhost, iothreads) | libvirt domain XML, generated from the inventory |
| Containers (Podman via systemd quadlets) | `CPUAffinity=` / `CPUSchedulingPolicy=` in the unit |
| NIC IRQ threads | `/etc/nic-irq-affinity.conf` |
| Operator tools (SV generator, sniffer, capture) | `taskset` / `chrt` by hand |

That fragmentation is the root of everything below.

## 2. The problem

### 2.1 The placement decision is taken at the wrong time

A VM's affinity is frozen at deployment time, in the inventory:

```yaml
cpuset: [4, 6]        # vCPU cores
emulatorpin: 8        # QEMU emulator thread
rt_priority: 90
```

which renders as a fixed `<cputune>` block. The core numbers are chosen by a human, from a spreadsheet view of the node. But the right answer is only knowable **when the workload starts, on the actual node**: that is when topology and real occupancy are both known.

### 2.2 Static pinning and live migration are incompatible

The blocking one for cluster mode. If a VM's XML says "cores 4 and 6", those cores must stay free **on every node the VM could land on**. With N migratable VMs on a 3 node cluster, the operator hand-solves a global placement problem and re-solves it on every add, resize or removal. Hence:

- **Conflicts.** Two VMs designed independently both ask for cores 4 and 6. They coexist until Pacemaker puts them on the same node after a failure, then they silently share cores. Nothing detects it.
- **Waste.** Avoiding that means reserving cores defensively on all nodes for VMs that are not running there. The scarcest resource on the machine sits idle by construction.

### 2.3 No shared view of the pool

"Who owns which isolated core" is answerable nowhere: the VM inventory, the quadlet units, the IRQ file and whatever the operator typed in a terminal are four separate worlds. An operator pins an SV generator by hand with no idea what is taken; a container deployed later can legitimately be given a core a VM already uses; overlaps are errors nowhere, just latency found later during a cyclictest campaign or in production.

### 2.4 Failures are silent, and silently lose real time

When the placement cannot be honoured (core taken, pool exhausted, unexpected topology), nothing fails loudly. The workload runs, without the RT guarantees it was designed for. For a protection function, "running without its latency guarantee" is exactly the state we must never be unable to see.

### 2.5 Hyper-Threading is not modelled

Two logical siblings share one physical core's execution resources, so two independent RT threads on a sibling pair interfere. Sometimes we want the whole physical core (sibling left idle), sometimes we do not. A flat list of core numbers cannot express that, so the distinction lives in conventions and comments.

### 2.6 Exclusivity is the only available answer

The model has one implicit isolation level: this core is mine. Right for an RT vCPU, wasteful for a NIC IRQ thread, a QEMU emulator thread or a low duty SV consumer, which each burn a full isolated core for a few percent of use. And since they are alone on it, their RT priorities never arbitrate against anything: priority becomes decorative. There is no way to say "these three low duty actors share one core, in this priority order".

## 3. What a solution has to respect

Non negotiable, from the domain:

- **Never prevent a workload from starting.** A pinning problem must degrade the workload, not deny service. A degraded protection VM is bad; one that did not start is an outage.
- **No new single point of failure**, boot ordering dependency, or component whose crash leaves the node undefined.
- **Playbooks re-run on live substations.** Tolerate re-application, and recover from crashes, kills and reboots with no cleanup procedure.
- **Zero per-node configuration in the workload definition**, otherwise migration is back to square one.
- **Everything observable.** Any deviation from the requested placement must be visible in monitoring, with enough context to know what lost what.

## 4. Proposed approach

The single idea: **replace static placement by a declaration of intent, resolved at launch time against the live state of the node.** An actor says "one isolated core, FIFO 90, alone on its physical core"; the node decides which core, when it starts.

### 4.1 Declare intent, not core numbers

The inventory stops naming cores and names **isolation levels**:

| Level | Meaning |
|---|---|
| `none` | housekeeping, the Linux scheduler decides |
| `exclusive_logical` | one dedicated isolated logical core |
| `exclusive_physical` | one whole physical core, HT sibling kept idle |

This is the actual engineering requirement and the part that is stable across nodes and over time; "core 6" is an implementation detail of one node on one day. It also makes HT first class (2.5) instead of conventional, and lets a fleet be audited on what each VM *asked for* rather than what it got.

### 4.2 Resolve at start and at migration arrival

The resolution point for a VM is a **libvirt hook**, called on every lifecycle event. It runs on the destination node at start and at incoming live migration, the only place a per node, per instant decision can be taken. Migration comes for free: arriving on a new node is just another allocation round on that node's pool.

The hook must **always exit 0**; a non zero exit aborts the VM. That directly encodes the "never prevent a workload from starting" constraint.

### 4.3 The profile travels with the workload

For VMs, the intent is stored as **Ceph RBD image metadata** on the VM's disk, not in the node's configuration: the disk is the one thing that follows the VM everywhere, so the profile is always there and the local node resolves it against its own topology. That is what makes 2.2 go away rather than move somewhere else.

No new authoring surface: the inventory stays where everything is written. Quadlets are pushed from it by Ansible, and VM profiles would be pushed by `vm_manager`, which already owns RBD metadata and is the natural place to write the profile at creation and propagate it on clone. RBD is where the intent *lives and travels*, not where it is authored.

**The carrier is per mode, the mechanism is not.** A standalone VM's disk is local and carries nothing, so its profile is written to `/etc/seapath/alloc.d/<vm>.yaml` by the same Ansible run, from the same inventory variable. The hook reads RBD first, then the file, so a leftover local file cannot override a profile meant to travel. The alternative, a second mechanism doing the same job for standalone, is more work than a second carrier.

Standalone is worth covering because a profile expresses what a static `<cputune>` cannot: colocation through slots, priority relations with a NIC IRQ, a container or an operator tool, and above all the placement and priority of **vhost threads**. `<emulatorpin>` does reach the vhost threads, but together with the emulator thread, as one core set for both, and there is no vhost counterpart to `<emulatorsched>`, so their policy and priority cannot be stated apart either. Those two workloads have opposite needs: vhost carries the guest's SV and GOOSE traffic and wants FIFO, the emulator does housekeeping and should stay SCHED_OTHER, ideally off the isolated cores. Even the minimal split (different policies, same cores) needs a hook; once a hook exists, separate cores cost nothing more.

### 4.4 The pool state is derived from the kernel, not stored

"What is already taken" is **read from the kernel at every request**: thread affinities from `/proc`, IRQ affinities from `/proc/irq`, topology from `/sys`. A thread counts as occupying isolated cores only if its affinity mask is a subset of the isolated set, so unpinned threads do not pollute the accounting.

Not a database or a daemon, because:

- A database goes stale (crashed VM, interrupted hook, reboot), and then needs a reconciliation loop and a rule for who is right.
- Live rediscovery is **self healing by construction**: when a VM dies its threads leave `/proc` and its cores are free on the next read. No release protocol, no cleanup, no orphan state.
- A daemon adds a boot dependency, a crash surface and a restart protocol on every upgrade, on a machine whose whole point is predictability.

The kernel is never wrong about itself.

### 4.5 Serialisation by a kernel primitive

Concurrent allocations (two VMs migrating in at once, a container starting while a VM boots) are serialised by an **exclusive `flock`** on a file in `/run`, held across discover, allocate and apply. Once the pinning is applied the next caller sees it in `/proc`, so no lock manager, IPC or arbitration service is needed. `/run` is tmpfs, so no stale lock survives a reboot, and a kernel primitive cannot crash on us.

### 4.6 Claims for the actors the kernel cannot attribute

QEMU threads are discoverable from `/proc`; containers and third party processes are not. They register a **claim** (label, PID, cores) in a small runtime file that the pool reads alongside the kernel sources, and a claim whose PID is gone is dropped on the next read. Self healing is preserved through process liveness, a kernel fact, rather than a release protocol a crash can skip. NIC IRQs deliberately do not use claims: they have no PID and the kernel already exposes their affinity, so they are read passively.

### 4.7 Degrade in a documented order, and record it

When the requested level cannot be satisfied, the allocator walks a fixed ladder rather than failing: `exclusive_physical`, then `exclusive_logical` (RT isolation kept, HT noise possible), then housekeeping (RT isolation lost).

Those two outcomes are **not** the same severity and must not be reported the same way: losing an idle HT sibling is a performance concern, losing isolation means the actor no longer has a real time guarantee. Every degradation is logged and exported with its severity and context. This is the direct answer to 2.4: the system may give you less than you asked for, never quietly.

### 4.8 Placement strategies are a node level policy

How free cores are picked matters as much as which, because of HT. The node exposes a strategy: **spread** one thread per physical core (best HT isolation), **pack** siblings first (density), or **repack**, compacting existing threads to free a whole physical pair before an `exclusive_physical` request falls back.

It is a policy rather than a hardcoded choice because density versus HT quietness is a site decision. Repacking is what lets a fragmented pool still honour a strict request, the common case on a node that has run for months.

### 4.9 Named shared core slots for controlled colocation

To answer 2.6, an object between the actor and the core: a **slot**, a named group of isolated cores shared by several actors, each keeping its own scheduling policy and priority. The point is not only density. Once several actors share a core, their RT priorities finally arbitrate against each other, which is the actual mechanism behind "the IRQ thread always wins over the consumer that reads its packets". Exclusivity cannot express that relation at all.

Two rules make slots usable in a cluster:

- **The name is the whole coordination mechanism.** Slot names are host global and resolved locally: `slot: sv0` means "this node's sv0", whichever node the VM lands on. Workload definitions stay node agnostic (4.3) while still targeting something node specific.
- **The fixed actor publishes its position, mobile actors join it by name.** A NIC IRQ is bound to the machine and its core is an operator decision from the inventory, so it declares its slot. VMs, containers and tools move, so their cores are allocated from the pool at first reference. Never the reverse: asking the pool for a placement that can never be released is a static assignment in disguise, with an availability dependency for no gain.

Colocation can be dangerous (sharing a core with an RT vCPU can stall a guest kernel), so the rule is **warn, never refuse**: the operator is the authority on their own machine, and a mechanism that can refuse can prevent a VM from starting. Risky patterns are detected and exported as metrics instead.

### 4.10 Observability is part of the feature, not an add on

Placement being dynamic, "which core is this VM on" stops being answerable from the inventory, so the system must answer it: pool occupancy per actor, current degradations with their severity, and risky colocations, exported through the existing node_exporter textfile path so the collection infrastructure does not change. Not optional: dynamic allocation trades a decision the operator used to make by hand for one the node makes, and that trade only holds if the outcome stays at least as visible as before.

Concretely, a Grafana dashboard of who holds which core, plus alerting rules for pool exhaustion and degradation. The rules ship as documentation to paste into the site's own Prometheus configuration rather than as deployed configuration: the supervision stack is site owned and not managed by this repo.

## 5. What this adds, and what keeps working

An **additional way of doing things, not a replacement**. Nothing that works today stops working, and adoption is per workload.

| Today | With seapath-alloc |
|---|---|
| `cpuset` / `emulatorpin` / `rt_priority` in the VM inventory | isolation intent in the VM profile, cores chosen at start |
| `CPUAffinity=` in quadlet units | pin helper in `ExecStartPost=`, cores from the pool |
| manual `taskset` / `chrt` by the operator | wrapper that claims cores, then execs the tool |
| static NIC IRQ affinity | unchanged, plus optional slot declaration so others can join |

The left column keeps working, by construction:

- **A VM with no profile is not touched.** The hook resolves it to an all `none` profile: no `taskset`, no `chrt`. A VM pinned by its `<cputune>` keeps exactly the placement its XML gave it.
- **Statically pinned VMs are still accounted for.** Occupancy comes from `/proc` for every QEMU thread, whoever pinned it, so an XML-pinned VM makes its cores unavailable to dynamic actors with no registration and no configuration. The two mechanisms do not fight, because the dynamic one observes the static one.
- **NIC IRQ configuration does not change**; it only becomes visible to the allocator.

The VM XML templates need no change either: everything inside `<cputune>` is already conditional on `cpuset` being defined, and the vCPU count already falls back to `nb_cpu`. A VM adopting a profile simply stops setting `cpuset` and renders the empty `<cputune>` every non-RT VM already renders. A VM keeping `cpuset` keeps its static pinning, forever if that suits it. The one thing not to do is set both on the same VM: libvirt would apply the XML at start and the hook would re-pin afterwards. Pick one per VM.

Nothing moves when the mechanism is deployed, and workloads opt in one at a time by being given a profile. That is what makes it landable on an existing fleet.

## 6. Out of scope

- NUMA awareness: SEAPATH targets single socket servers today.
- Changing a running workload's profile without a restart.
- Any "notify me when a core frees up" mechanism: no use case identified.
- Cluster wide placement (which node a VM runs on): that stays Pacemaker's job. This proposal is strictly per node.

## 7. Delivery: one reviewable step at a time

Each step is its own pull request and is self-contained: the modules it adds import cleanly and come with their own tests, so the series stays bisectable and a reviewer can run what they are reading.

| # | Step | What it adds |
|---|---|---|
| 1 | CPU topology reader and live core pool | `/sys` topology, live occupancy from `/proc`, passive NIC IRQ reading, `flock` serialisation |
| 2 | Allocation engine and HT repacker | pure logic: intent plus free cores gives placement, the degradation ladder, the three strategies |
| 3 | QEMU thread discovery and pinning application | thread classification, apply order vCPUs then emulator then vhost then iothreads |
| 4 | libvirt hook and the Ansible role | the full VM path, profile from RBD metadata, the deployable role |
| 5 | Claims registry, operator CLI, `seapath-run` | non-QEMU actors join the pool, pool state becomes inspectable |
| 6 | Container pinning for systemd quadlets | cgroup-level enforcement for multi-process services |
| 7 | Prometheus exporter and Grafana dashboards | pool and degradation metrics through the node_exporter textfile path |
| 8 | Named shared-core slots | controlled colocation and priority arbitration (4.9) |
| 9 | Pinning profile support in `vm_manager` | profile written at VM creation, propagated on clone |
| 10 | Local profile file for standalone VMs | second carrier, so standalone RT VMs are not limited to what `<cputune>` can express |

Steps 1 to 3 are library only and change no behaviour on a deployed node, so they can be one PR if a series of three is not worth the overhead. Step 4 is the first that does something. Steps 5 to 10 each stand alone and can land in any order after 4, except 8 which builds on 5 and 6; 9 and 10 are the two carriers and are independent. No step removes or rewrites an existing mechanism, so each can be merged, or refused, without holding up the others and without a migration on any deployed machine.

## 8. Points to discuss

**Default allocation strategy for the fleet.** `spreading` is the conservative default: one thread per physical core, best HT quietness, but it fragments the pool and a long lived node can end up unable to honour an `exclusive_physical` request while holding plenty of half used pairs. `repacking` keeps strict requests satisfiable by compacting first, at the cost of moving threads that already belong to running workloads. Which should be the shipped default, and is moving an existing RT thread acceptable on a live substation?
