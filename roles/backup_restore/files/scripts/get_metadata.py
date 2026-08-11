#!/usr/bin/env python3
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
"""Print the RBD image metadata keys of a guest's system disk."""
import sys

import rados
import rbd


def print_metadata_keys(guest):
    cluster = rados.Rados(conffile='/etc/ceph/ceph.conf')
    cluster.connect()
    try:
        ioctx = cluster.open_ioctx('rbd')
        try:
            with rbd.Image(ioctx, "system_" + guest) as image:
                for key, _ in image.metadata_list():
                    print(key)
        finally:
            ioctx.close()
    finally:
        cluster.shutdown()


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) != 2:
        print(f"usage: {argv[0]} <guest>", file=sys.stderr)
        sys.exit(1)
    print_metadata_keys(argv[1])


if __name__ == "__main__":
    main()
