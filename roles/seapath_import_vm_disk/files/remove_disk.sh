#!/bin/sh
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

set -e
rbd_pool="$1"
disk_name="$2"
if rbd list -p "$rbd_pool" | grep -q -E "^${disk_name}\$" ; then
    if rbd --pool "$rbd_pool" snap list --image "${disk_name}" ; then
        rbd --pool "$rbd_pool" snap purge "${disk_name}"
    fi
    rbd rm -p "$rbd_pool" "$disk_name"
fi
