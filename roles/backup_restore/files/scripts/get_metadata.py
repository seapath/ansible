#!/usr/bin/env python3
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
"""Print the RBD image metadata keys of a guest's system disk."""
import sys

import rados
import rbd

if len(sys.argv) != 2:
    print(f"usage: {sys.argv[0]} <guest>", file=sys.stderr)
    sys.exit(1)

cluster = rados.Rados(conffile='/etc/ceph/ceph.conf')
cluster.connect()
try:
    ioctx = cluster.open_ioctx('rbd')
    try:
        with rbd.Image(ioctx, "system_" + sys.argv[1]) as image:
            for key, _ in image.metadata_list():
                print(key)
    finally:
        ioctx.close()
finally:
    cluster.shutdown()
