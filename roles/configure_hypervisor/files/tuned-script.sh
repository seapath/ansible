#!/bin/bash
# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

. /usr/lib/tuned/functions

start() {
    setup_kvm_mod_low_latency
    for pid in $(pgrep rcuc); do
        chrt -f -p 10 "$pid" 2>/dev/null || true
    done
    return 0
}

stop() {
    if [ "$1" = "full_rollback" ]; then
        teardown_kvm_mod_low_latency
    fi
    return "$?"
}

verify() {
    return 0
}

process $@
