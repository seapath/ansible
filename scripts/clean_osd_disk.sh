#!/bin/sh
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

osd_disk="$1"

if lvs | grep -q osd-block ; then
    ceph-volume lvm zap "${osd_disk}" --destroy
else
    dd if=/dev/zero of="${osd_disk}" bs=40M count=1
fi
