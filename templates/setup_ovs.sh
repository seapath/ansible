#!/bin/sh
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# {{ ansible_managed }}

set -e

if [ -d /opt/setup/setup_ovs.d ] ; then
    /opt/setup/setup_ovs.d/*
fi
