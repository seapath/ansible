#!/bin/sh
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

set -e
vm_name="$1"
activate="$2"
enabled=
if [ "${activate}" = no ] ; then
    enabled='is-managed=false'
fi
crm config primitive "${vm_name}" \
   ocf:heartbeat:VirtualDomain \
   params config=/etc/pacemaker/"${vm_name}".xml \
   hypervisor="qemu:///system" \
   migration_transport="ssh" meta allow-migrate="true" \
   "${enabled}" \
   op start timeout="120s" \
   op stop timeout="120s" \
   op monitor timeout="30" interval="10" depth="0"
