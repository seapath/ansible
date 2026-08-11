#!/usr/bin/env python3
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
import sys
import lxml.etree as le


def remove_disks(src, dst):
    """Copy the libvirt domain XML at src to dst without its <disk> elements."""
    with open(src, 'r') as f:
        doc = le.parse(f)
        for elem in doc.xpath("//disk"):
            parent = elem.getparent()
            parent.remove(elem)
        doc.write(dst, pretty_print=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    remove_disks(argv[0], argv[1])


if __name__ == "__main__":
    main()
