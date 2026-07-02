# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

"""
Pinning profile loading and normalisation.

Priority chain (highest wins):
  1. Ceph RBD image metadata — key _seapath_alloc on the VM's system disk
  2. Built-in all-none profile — safe no-op on any host

A VM with no RBD metadata is treated as non-RT: all thread groups get
isolation=none, scheduler=OTHER, priority=0.

Host-wide settings (allocation_strategy) live in /etc/seapath/alloc.yaml
and are read separately by load_strategy().

RBD is accessed via the rbd CLI (not the Python bindings) to avoid a hard
dependency on librbd/librados, which may not be available on Yocto builds.

Profile YAML schema
-------------------
version: 1

# vcpus accepts two forms:
#
# Form 1 — uniform: one dict applies to all vCPUs
vcpus:
  isolation: exclusive_physical   # none | exclusive_logical | exclusive_physical
  scheduler: FIFO                 # FIFO | RR | OTHER | BATCH
  priority: 90                    # 1-99 for FIFO/RR, 0 for OTHER/BATCH
#
# Form 2 — per-vCPU: a list indexed by vCPU number.
# If the list is shorter than the actual vCPU count, the last entry is
# repeated for remaining vCPUs. Useful for mixed RT/non-RT VMs.
# vcpus:
#   - isolation: exclusive_physical   # vCPU 0
#     scheduler: FIFO
#     priority: 90
#   - isolation: none                  # vCPU 1 onwards → housekeeping
#     scheduler: OTHER
#     priority: 0

emulator:
  isolation: exclusive_logical
  scheduler: FIFO
  priority: 50
vhost:
  isolation: exclusive_logical
  scheduler: FIFO
  priority: 50
  # Optional: allocate a fixed number of cores shared by ALL vhost threads.
  # Without count, each vhost thread gets its own core (default behaviour).
  # count: 2
iothread:
  isolation: none
  scheduler: OTHER
  priority: 0

# Any group may reference a named slot instead of requesting its own cores.
# A slot is a host-global named group of isolated cores: the first actor
# referencing the name allocates it (isolation describes the SLOT's level,
# default exclusive_logical), later actors share its cores with their own
# scheduler/priority. Example — emulator in TS and vhost in FIFO/1 on the
# same core:
# emulator:
#   slot: housework
#   scheduler: OTHER
# vhost:
#   slot: housework
#   scheduler: FIFO
#   priority: 1

All keys are optional — missing keys are filled from built-in defaults.
count (vhost/iothread only): when present, a single allocation of <count>
  cores is made for the whole group; all threads of that group share them.
  Without count, each thread receives its own core.
slot (any group): name of a host-global shared-core slot. isolation then
  applies to the slot at creation time and must not be none.
"""

import logging
import os
import subprocess
import xml.etree.ElementTree as ET

try:
    import yaml
except ImportError:
    # pyyaml not available; profile loading falls back to built-in all-none.
    # Install python3-yaml to enable per-VM profiles.
    yaml = None

log = logging.getLogger(__name__)

_SETTINGS_FILE = "/etc/seapath/alloc.yaml"

_BUILTIN_DEFAULT = {
    "isolation": "none",
    "scheduler": "OTHER",
    "priority": 0,
}

_GROUP_KEYS = ("vcpus", "emulator", "vhost", "iothread")


def _run(cmd: list, timeout: int = 5):
    """Run a command; return stdout text or None on any error."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            log.debug("command failed: %s\nstderr: %s", " ".join(cmd), r.stderr.strip())
            return None
        return r.stdout
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("command error %s: %s", " ".join(cmd), exc)
        return None


def _vcpu_count_from_xml(domain_xml: str) -> int:
    """Extract vCPU count from libvirt domain XML (passed on stdin by libvirt)."""
    try:
        root = ET.fromstring(domain_xml)
        el = root.find("vcpu")
        if el is not None:
            # <vcpu current='N'>MAX</vcpu>: at start only N vCPU threads exist
            # (the rest are hot-pluggable). Prefer current so discovery doesn't
            # wait the full timeout for threads that aren't there yet.
            current = el.get("current")
            if current:
                return int(current)
            if el.text:
                return int(el.text.strip())
    except Exception:
        pass
    return 0


def _rbd_source_from_xml(domain_xml: str) -> str:
    """
    Extract the RBD pool/image path from libvirt domain XML.

    Looks for <disk type="network"><source protocol="rbd" name="pool/img"/></disk>.
    """
    try:
        root = ET.fromstring(domain_xml)
        for disk in root.findall('.//disk[@type="network"]'):
            src = disk.find('source[@protocol="rbd"]')
            if src is not None:
                name = src.get("name", "")
                if name:
                    return name
    except Exception:
        pass
    return ""


def get_vcpu_count(vm_name: str, virsh_bin: str = "virsh",
                   domain_xml: str = "") -> int:
    """
    Return the current vCPU count for vm_name.

    Tries the domain XML first (passed on stdin by libvirt — no subprocess).
    Falls back to `virsh vcpucount` for callers outside the hook context.
    """
    if domain_xml:
        count = _vcpu_count_from_xml(domain_xml)
        if count > 0:
            return count
        log.debug("could not parse vcpu count from XML for %s", vm_name)

    out = _run([virsh_bin, "vcpucount", vm_name, "--current"])
    if out is None:
        log.warning("could not get vcpu count for %s, assuming 1", vm_name)
        return 1
    try:
        return int(out.strip())
    except ValueError:
        log.warning("unexpected vcpucount output for %s: %r", vm_name, out)
        return 1


def get_rbd_source(vm_name: str, virsh_bin: str = "virsh",
                   domain_xml: str = "") -> str:
    """
    Return the pool/image RBD path for vm_name's primary disk, or ''.

    Tries the domain XML first (passed on stdin by libvirt — no subprocess).
    Falls back to `virsh domblklist` for callers outside the hook context.
    """
    if domain_xml:
        path = _rbd_source_from_xml(domain_xml)
        if path:
            return path
        log.debug("no RBD disk found in XML for %s", vm_name)

    out = _run([virsh_bin, "domblklist", vm_name, "--details"])
    if out is None:
        return ""
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        source = parts[3]
        # An RBD source is always "pool/image". Requiring the slash also
        # skips the "Type Device Target Source" header row, whose 4th token
        # would otherwise be returned as a disk source.
        if "/" in source and not source.startswith("/"):
            return source
    return ""


def get_pinning_metadata(vm_name: str,
                         virsh_bin: str = "virsh",
                         rbd_bin: str = "rbd",
                         domain_xml: str = "") -> str:
    """
    Fetch the raw YAML stored in the RBD image metadata key _seapath_alloc.

    Returns the YAML string, or '' if not found.
    """
    rbd_path = get_rbd_source(vm_name, virsh_bin, domain_xml=domain_xml)
    if not rbd_path:
        log.debug("no RBD disk found for %s", vm_name)
        return ""
    out = _run([rbd_bin, "image-meta", "get", rbd_path, "_seapath_alloc"])
    if out is None:
        log.debug("no _seapath_alloc metadata on %s", rbd_path)
        return ""
    return out.strip()


def _normalize_group(spec) -> dict:
    if not isinstance(spec, dict):
        spec = {}
    merged = dict(_BUILTIN_DEFAULT)
    merged.update(spec)
    # A slot reference without an explicit isolation means "a shared isolated
    # core" — the slot's isolation level defaults to exclusive_logical, never
    # none (a housekeeping slot would have no cores to share).
    if merged.get("slot"):
        merged["slot"] = str(merged["slot"])
        if "isolation" not in spec:
            merged["isolation"] = "exclusive_logical"
    else:
        merged.pop("slot", None)
    # Non-none isolation without an explicit scheduler implies RT intent → FIFO.
    if merged["isolation"] != "none" and "scheduler" not in spec:
        merged["scheduler"] = "FIFO"
    # RT schedulers without an explicit priority default to 1 (minimum valid RT).
    if merged["scheduler"] in ("FIFO", "RR") and "priority" not in spec:
        merged["priority"] = 1
    # OTHER/BATCH always force priority to 0.
    if merged["scheduler"] in ("OTHER", "BATCH"):
        merged["priority"] = 0
    if "count" in merged:
        merged["count"] = max(1, int(merged["count"]))
    return merged


def normalize_profile(raw: dict) -> dict:
    """
    Fill missing group keys and missing per-key values from built-in defaults.

    vcpus may be either a dict (uniform — same config for all vCPUs) or a
    list (per-vCPU — each entry applies to the corresponding vCPU; the last
    entry is repeated for any remaining vCPUs beyond the list length).

    Guarantees that downstream code can always index profile["vcpus"] as a
    dict or list without KeyError, regardless of how sparse the user's YAML is.
    """
    profile = {}
    for key in _GROUP_KEYS:
        user_spec = raw.get(key, {})
        if key == "vcpus" and isinstance(user_spec, list):
            normalized = [_normalize_group(entry) for entry in user_spec]
            profile[key] = normalized if normalized else [_normalize_group({})]
        else:
            profile[key] = _normalize_group(user_spec)
    return profile


def load_profile(vm_name: str,
                 virsh_bin: str = "virsh",
                 rbd_bin: str = "rbd",
                 domain_xml: str = "") -> dict:
    """
    Load and normalise the pinning profile for vm_name.

    Falls through: RBD metadata → built-in all-none.

    A VM with no RBD metadata is treated as non-RT (isolation=none everywhere).

    domain_xml: full libvirt domain XML string (passed on stdin by the hook).
    When provided, disk discovery and vCPU count are read from the XML directly
    without calling virsh, which avoids subprocess failures inside the hook
    environment where the libvirt socket URI may not be inherited.
    """
    if yaml is None:
        log.warning("pyyaml not available; using built-in all-none for %s", vm_name)
        return normalize_profile({})

    # 1. RBD image metadata
    raw_yaml = get_pinning_metadata(vm_name, virsh_bin, rbd_bin,
                                    domain_xml=domain_xml)
    if raw_yaml:
        try:
            raw = yaml.safe_load(raw_yaml)
            if isinstance(raw, dict):
                log.info("loaded pinning profile from RBD metadata for %s", vm_name)
                return normalize_profile(raw)
        except yaml.YAMLError as exc:
            log.warning("invalid YAML in RBD metadata for %s: %s", vm_name, exc)

    # 2. Built-in all-none
    log.info("no pinning profile for %s — running on housekeeping cores", vm_name)
    return normalize_profile({})


def load_strategy(settings_file: str = _SETTINGS_FILE):
    """
    Read the allocation_strategy key from /etc/seapath/alloc.yaml.

    Returns an AllocationStrategy value; defaults to SPREADING when the key
    is absent, the file is missing, or the value is unrecognised.
    """
    from .allocator import AllocationStrategy
    if yaml is None:
        return AllocationStrategy.SPREADING
    if not os.path.exists(settings_file):
        return AllocationStrategy.SPREADING
    try:
        with open(settings_file) as fh:
            raw = yaml.safe_load(fh)
        if isinstance(raw, dict):
            val = raw.get("allocation_strategy", "spreading")
            try:
                return AllocationStrategy(str(val).lower())
            except ValueError:
                log.warning("unknown allocation_strategy %r, using spreading", val)
    except (OSError, yaml.YAMLError) as exc:
        log.warning("could not read allocation_strategy from %s: %s", settings_file, exc)
    return AllocationStrategy.SPREADING


def expand_group_specs(profile: dict,
                       vcpu_count: int,
                       vhost_count: int,
                       iothread_count: int) -> list:
    """
    Expand a normalised profile into an ordered list of per-thread-group specs.

    Order: vCPUs → emulator → vhost → iothreads.
    This order matches the apply order required by applier.py (vhost threads
    inherit emulator affinity at creation; emulator must be pinned first).

    profile["vcpus"] may be a dict (uniform) or a list (per-vCPU). When a
    list, entry i applies to vCPU i; the last entry is repeated for vCPUs
    beyond the list length.

    Returns a list of dicts: [{name, isolation, scheduler, priority}, ...]
    """
    specs = []

    vcpu_spec = profile["vcpus"]
    if isinstance(vcpu_spec, list):
        for i in range(vcpu_count):
            entry = vcpu_spec[min(i, len(vcpu_spec) - 1)]
            s = dict(entry)
            s["name"] = f"vcpu/{i}"
            specs.append(s)
    else:
        for i in range(vcpu_count):
            s = dict(vcpu_spec)
            s["name"] = f"vcpu/{i}"
            specs.append(s)

    s = dict(profile["emulator"])
    s["name"] = "emulator"
    specs.append(s)

    vhost_spec = profile["vhost"]
    if vhost_count > 0:
        if "count" in vhost_spec:
            s = dict(vhost_spec)
            s["name"] = "vhost"
            specs.append(s)
        else:
            for i in range(vhost_count):
                s = dict(vhost_spec)
                s["name"] = f"vhost/{i}"
                specs.append(s)

    iothread_spec = profile["iothread"]
    if iothread_count > 0:
        if "count" in iothread_spec:
            s = dict(iothread_spec)
            s["name"] = "iothread"
            specs.append(s)
        else:
            for i in range(iothread_count):
                s = dict(iothread_spec)
                s["name"] = f"iothread/{i}"
                specs.append(s)

    return specs
