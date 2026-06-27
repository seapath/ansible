#!/bin/bash
# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0
#
# Script plugin of the seapath-rt-host tuned profile.
#
# seapath-rt-host includes realtime-virtual-host, and declaring [script] here
# overrides the script inherited from that base profile: its own script.sh is
# no longer executed. Its KVM low latency setup is therefore reproduced below,
# and must be kept in sync with the base profile.
#
# The rcuc priority tuning replaces the [scheduler] group.rcuc rule of the base
# profile, which no longer applies since the scheduler plugin is disabled: its
# perf_event mmap() calls stall CPUs on RT kernels when the profile is applied.

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
