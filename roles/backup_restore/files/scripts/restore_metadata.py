#!/usr/bin/env python3
# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0
"""Write back on an RBD image the metadata a backup exported.

Usage: restore_metadata.py <pool>/<image> <file>

<file> is what `rbd image-meta list --format json` printed when the backup
was taken, an object of keys and values, or nothing at all for an image
without metadata. The values are written through the Ceph bindings rather
than `rbd image-meta set`, whose value is one command-line argument, limited
to 128 KiB: the definition deploy_containers_cluster records on a workload's
image carries its quadlets and configuration files and may be larger.
"""
import json
import sys

import rados
import rbd


def read_metadata(path):
    with open(path, encoding="utf-8") as stream:
        text = stream.read().strip()
    return json.loads(text) if text else {}


def image_spec(spec):
    """`<pool>/<image>` as its two parts."""
    pool, _, name = spec.partition("/")
    if not pool or not name:
        raise ValueError(f"{spec} is not <pool>/<image>")
    return pool, name


def restore_metadata(spec, metadata, conffile="/etc/ceph/ceph.conf"):
    """Set every key of `metadata` on `spec`, `<pool>/<image>`; return them."""
    pool, name = image_spec(spec)
    cluster = rados.Rados(conffile=conffile)
    cluster.connect()
    try:
        ioctx = cluster.open_ioctx(pool)
        try:
            with rbd.Image(ioctx, name) as image:
                for key in sorted(metadata):
                    image.metadata_set(key, metadata[key])
        finally:
            ioctx.close()
    finally:
        cluster.shutdown()
    return sorted(metadata)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) != 3:
        print(f"usage: {argv[0]} <pool>/<image> <file>", file=sys.stderr)
        sys.exit(1)
    try:
        image_spec(argv[1])
        keys = restore_metadata(argv[1], read_metadata(argv[2]))
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    for key in keys:
        print(f"metadata name = {key}")


if __name__ == "__main__":
    main()
