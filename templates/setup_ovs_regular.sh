#!/bin/sh
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# {{ ansible_managed }}
set -e

if ovs-vsctl br-exists "{{ item.name }}" ; then
    ovs-vsctl del-br "{{ item.name }}"
fi
ovs-vsctl add-br "{{ item.name }}"
ovs-vsctl add-port "{{item. name }}" "{{ item.interface }}"
