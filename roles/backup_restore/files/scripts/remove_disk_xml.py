#!/usr/bin/env python3
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
import sys
import lxml.etree as le

s = sys.argv[1]
d = sys.argv[2]

with open(s,'r') as f:
    doc=le.parse(f)
    for elem in doc.xpath("//disk"):
        parent=elem.getparent()
        parent.remove(elem)
    doc.write(d, pretty_print = True)
