#!/usr/bin/env python3
# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0
"""Print the RBD images of the container workloads, one per line.

deploy_containers_cluster names the RBD image of a workload after the
workload, and records in its metadata, under seapath.images, the container
images it was deployed with. That key is what tells the state of a workload
from the other images of the pool: a guest's disks are system_<guest> and
data_<guest>_<n>, and carry no such key.

An image the role put aside when it recreated a workload keeps the key, and
its name, <name>.<date>-<version>, has a dot no workload name has. It is not
the state of a running workload, and it is left out.
"""
import sys

import rados
import rbd

KEY = "seapath.images"


def list_containers(conffile="/etc/ceph/ceph.conf", pool="rbd"):
    cluster = rados.Rados(conffile=conffile)
    cluster.connect()
    try:
        ioctx = cluster.open_ioctx(pool)
        try:
            names = []
            for name in sorted(rbd.RBD().list(ioctx)):
                if "." in name:
                    continue
                try:
                    with rbd.Image(ioctx, name, read_only=True) as image:
                        keys = [key for key, _ in image.metadata_list()]
                except rbd.ImageNotFound:
                    # Removed between the listing and now.
                    continue
                if KEY in keys:
                    names.append(name)
            return names
        finally:
            ioctx.close()
    finally:
        cluster.shutdown()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) != 1:
        print(f"usage: {argv[0]}", file=sys.stderr)
        sys.exit(1)
    for name in list_containers():
        print(name)


if __name__ == "__main__":
    main()
