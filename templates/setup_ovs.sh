#!/bin/sh
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# {{ ansible_managed }}

set -e

dpdk_module="{{ dpdk_module | default() }}"

if [ -n "${dpdk_module}" ] ; then
    modprobe "${dpdk_module}"
fi

if [ -d /opt/setup/setup_ovs.d ] ; then
    run-parts /opt/setup/setup_ovs.d
fi

chown :qemu /var/run/openvswitch
chmod 775 /var/run/openvswitch
