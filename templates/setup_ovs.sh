#!/bin/sh
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# {{ ansible_managed }}

set -e

modprobe "{{ dpdk_module }}"
dpdk-devbind --force  --bind="{{ dpdk_module }}" "{{ dpdk_nic }}"
if ip addr |grep -q "ovsbr:" ; then
    ovs-vsctl del-br ovsbr
fi
ovs-vsctl add-br ovsbr -- set bridge ovsbr datapath_type=netdev
ovs-vsctl add-port ovsbr dpdk-p0 -- set Interface dpdk-p0 type=dpdk \
    "options:dpdk-devargs={{ dpdk_nic }}"
    for i in $(seq 0 $(({{ ovs_number_of_virtual_ports }} -1))) ; do
    ovs-vsctl add-port ovsbr dpdkvhostuser$i -- set Interface dpdkvhostuser$i \
        type=dpdkvhostuserclient
    ovs-vsctl set Interface dpdkvhostuser$i \
        options:vhost-server-path="/var/run/openvswitch/dpdkvhostuser$i"
done
chmod 777 /var/run/openvswitch
