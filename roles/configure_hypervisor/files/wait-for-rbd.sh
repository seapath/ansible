#!/bin/bash
# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0
#
# wait-for-rbd.sh - block until a Ceph RBD pool can be listed.
#
# Usage: wait-for-rbd.sh [<pool>]
#
# Used as the ExecStart of ceph-rbd-ready.service, the readiness gate that
# quadlet containers with an RBD-backed volume order themselves after.  At
# boot the cluster typically needs a minute or two to form a quorum, which is
# long after network-online.target: without this gate the seapath-rbd-mount
# call in ExecStartPre= fails, and the retries allowed by Restart= burn
# through StartLimitBurst before Ceph is up.
#
# "rbd ls" is the readiness criterion rather than a mon ping: it is exactly
# what seapath-rbd-mount needs to succeed (mon quorum reached, OSD map
# received, pool present and readable with the local keyring).
#
# Each attempt is wrapped in "timeout" because rbd retries a mon connection on
# its own for far longer than the interval below, which would otherwise make
# the loop deadline meaningless.
#
# Exit: 0 as soon as the pool answers, 1 if it never does within the deadline.

pool="${1:-rbd}"
timeout=300  # seconds
interval=10
attempt_timeout=15
end=$((SECONDS + timeout))

while [ $SECONDS -lt $end ]; do
    if timeout "$attempt_timeout" rbd --pool "$pool" ls > /dev/null 2>&1; then
        echo "Ceph pool $pool is reachable."
        exit 0
    fi

    echo "Waiting for Ceph pool $pool ..."
    sleep $interval
done

echo "Ceph pool $pool not reachable after $timeout seconds."
exit 1
