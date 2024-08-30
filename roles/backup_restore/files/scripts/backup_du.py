#!/usr/bin/env python3
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
## ------------------------------
## Backup DU
## Estimating volume Backup
## ------------------------------
from subprocess import check_output
import sys

FMT_LIG = "%-20s %10d"

def convert_size(nb, unit):
    match unit.upper():
        case "GIB":
            size = float(nb)*1024*1024*1024
        case "MIB":
            size = float(nb)*1024*1024
        case "KIB":
            size = float(nb)*1024
        case _:
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

def read_du_rbd(data):
    volume={}
    cmd = '/usr/bin/rbd du 2>/dev/null | grep system_'
    if data["include_vm"] and data["include_vm"] != '""':
        cmd += '| grep -E "(%s)"' % data["include_vm"].replace('"', '')
    if data["exclude_vm"] and data["exclude_vm"] != '""':
        cmd += '| grep -v -E "(%s)"' % data["exclude_vm"].replace('"', '')

    out = check_output(cmd, shell=True, text=True, universal_newlines=True)
    for l in out.split('\n'):
        if l:
            name, prov, punit, used, uunit = l.split()
            name = name.replace("system_","")
            if '@' in name:
                name = name[0:name.index('@')]
            t = convert_mo(convert_size(used, uunit))
            if name in volume:
                volume[name] += t
            else:
                volume[name] = t
    return volume


def compute():
    data = {}
    data["include_vm"] = sys.argv[1]
    data["exclude_vm"] = sys.argv[2]
    volume = read_du_rbd(data)
    pr_table(volume)

if __name__ == "__main__":
    compute()
