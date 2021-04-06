#!/bin/sh
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# {{ ansible_managed }}


dpdk-devbind --force  --bind=vfio-pci "{{ item.nic }}"
if ovs-vsctl br-exists "{{ item.name }}" ; then
    ovs-vsctl del-br "{{ item.name }}"
fi
ovs-vsctl add-br "{{ item.name }}" -- set bridge "{{ item.name }}" \
    datapath_type=netdev
ovs-vsctl add-port "{{ item.name }}" dpdk-p0 -- set Interface dpdk-p0 \
    type=dpdk "options:dpdk-devargs={{ item.nic }}"
for i in $(seq 0 $(({{ item.number_of_virtual_ports }} -1))) ; do
    ovs-vsctl add-port "{{ item.name }}" dpdkvhostuser$i -- set Interface \
        dpdkvhostuser$i type=dpdkvhostuserclient
    ovs-vsctl set Interface dpdkvhostuser$i \
        options:vhost-server-path="/var/run/openvswitch/dpdkvhostuser_{{ item.name }}$i"
done
