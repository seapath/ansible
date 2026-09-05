# hwlatdetect Role

This role runs `hwlatdetect` and fetches the result.

It measures what every other real time check on a SEAPATH machine is blind to:
interruptions the kernel never sees. A System Management Interrupt takes the
CPU into firmware, and the operating system is not told it happened, so the
time is missing from the kernel's own accounting and from `cyclictest`'s view
of it. `hwlatdetect` finds them by polling the TSC in a tight loop with
interrupts disabled and reporting the gaps.

That makes it the answer to a question the rest of the tuning cannot settle: a
machine that is correctly isolated and still misses its deadline is either a
firmware problem or a configuration one, and this is what tells the two apart.

## Requirements

- `hwlatdetect`, from the `rt-tests` package. The role checks for it and fails
  naming the package. Nothing here installs it: a measurement must change
  nothing on the machines it measures.
- A kernel built with `CONFIG_HWLAT_TRACER`. The role checks for the tracer and
  records its absence in the result rather than failing.

The two checks are deliberately different. A missing package is a machine that
was not prepared, and the same machine answers as soon as it is, so the run
stops and says which package. A missing tracer is a property of the kernel
build that no package fixes, so a machine that will never answer is an expected
state: a measurement plays every machine of the inventory, and one kernel that
cannot answer must not take down a run that has already loaded the others.

## Role Variables

| Variable                   | Required | Type   | Default | Comments                                                        |
|----------------------------|----------|--------|---------|-----------------------------------------------------------------|
| hwlatdetect_result_folder  | No       | String | ..      | Path where the result is stored                                 |
| hwlatdetect_duration       | No       | Int    | 120     | Duration of the test in seconds                                 |
| hwlatdetect_window         | No       | Int    | 1000000 | Microseconds between the start of one sampling period and the next |
| hwlatdetect_width          | No       | Int    | 500000  | Microseconds spent sampling within each window                  |
| hwlatdetect_threshold      | No       | Int    | 10      | Microseconds below which a gap is not reported                  |

`width` out of every `window` is the fraction of wall clock time the hardware
is actually watched: at the defaults the detector is looking half the time, so
a 120 second run observes 60 seconds of the machine. Raising the fraction finds
rarer events and blocks the CPU it is watching for longer.

## Not for a machine in production

The hwlat thread moves to another CPU at the start of every window, round-robin
over `tracing_cpumask`, which is every CPU by default. The isolated cores
carrying the real time guests are sampled like the rest, and that is the point:
the SMI worth finding is the one that hits an isolated core.

It is also the cost. On the window where the thread lands on a core, that core
runs `width` microseconds with interrupts disabled, 0.5s at the defaults. The
rotation spreads it: on a 24 core machine, a 120s run blocks each core about
2.5s in total, in 0.5s slices.

A 0.5s slice is far beyond what a guest processing Sampled Values tolerates.
Run this on a machine that carries no live traffic: a bench, a new machine
before it is put in service, or one taken out of the cluster. That is also why
this role is not part of `seapath_setup_main.yaml`.

## Example Playbook

```yaml
- hosts: cluster_machines
  roles:
    - { role: seapath_ansible.hwlatdetect }
```

Or through the playbook that wraps it:

```
ansible-playbook seapath.ansible.test_run_hwlatdetect
```
