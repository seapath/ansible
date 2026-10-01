#!/usr/bin/env python3
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
## ------------------------------
## Backup DU
## Estimating volume Backup
## ------------------------------
from subprocess import check_output
import re
import sys

FMT_LIG = "%-20s %10d"

def convert_size(nb, unit):
    unit = unit.upper()
    if unit == "GIB":
        size = float(nb) * 1024 * 1024 * 1024
    elif unit == "MIB":
        size = float(nb) * 1024 * 1024
    elif unit == "KIB":
        size = float(nb) * 1024
    else:
        size = 0

    return int(size+0.5)

def convert_mo(nb):
    return int( (nb/1000/1000)+0.5 )

def pr_lig(n, z, u):
    f = FMT_LIG+u
    print( f % (n,z) )

def pr_table(d):
    total = 0
    for k,v in d.items():
        pr_lig(k, v, " MB")
        total += v

    print("-" * 35 )
    pr_lig("TOTAL :", total, " MB")
    print()
    pr_lig(" Estimating En GB",  int((total/1000)+0.5), " GB" )

def image_to_owner(name, containers=()):
    """Map an image name (system_<guest>, data_<guest>_<n>, or the image of a
    container workload, named after it) to the guest or workload owning it."""
    if '@' in name:
        name = name[0:name.index('@')]
    if name in containers:
        return name
    if name.startswith("system_"):
        return name[len("system_"):]
    if name.startswith("data_"):
        return name[len("data_"):].rsplit("_", 1)[0]
    return None

def read_du_rbd(data):
    volume={}
    include_vm = data["include_vm"].replace('"', '') or ".*"
    exclude_vm = data["exclude_vm"].replace('"', '')
    containers = check_output(
        ["python3", "/usr/local/bin/get_containers.py"], text=True
    ).split()
    # A workload name is letters, digits, dashes and underscores: nothing a
    # regular expression reads otherwise. Its rows are the image, then
    # <name>@<snapshot>.
    pattern = "(system|data)_"
    if containers:
        pattern = "((system|data)_|(" + "|".join(containers) + ")[@ ])"
    cmd = '/usr/bin/rbd du 2>/dev/null | grep -E "^' + pattern + '"'

    out = check_output(cmd, shell=True, text=True, universal_newlines=True)
    for l in out.split('\n'):
        if l:
            name, prov, punit, used, uunit = l.split()
            owner = image_to_owner(name, containers)
            if owner is None:
                continue
            if not re.search(include_vm, owner):
                continue
            if exclude_vm and re.search(exclude_vm, owner):
                continue
            t = convert_mo(convert_size(used, uunit))
            if owner in volume:
                volume[owner] += t
            else:
                volume[owner] = t
    return volume


def compute():
    data = {}
    data["include_vm"] = sys.argv[1]
    data["exclude_vm"] = sys.argv[2]
    volume = read_du_rbd(data)
    pr_table(volume)

if __name__ == "__main__":
    compute()
