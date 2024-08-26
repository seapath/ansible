#!/bin/sh
# Copyright (C) 2023, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

TMPDIR="/tmp/tmp-$USER"
mkdir -p "$TMPDIR"
chmod 700 $TMPDIR
export TMPDIR
readonly TMPDIR
