#!/bin/bash
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
# Wait until at least one MDS for "seapathcephfs" is active.

fs=$1
timeout=300  # seconds
interval=10
end=$((SECONDS + timeout))

while [ $SECONDS -lt $end ]; do
    status=$(ceph fs status $1 --format json)
    active_count=$(echo "$status" | jq '[.mdsmap[] | select(.state=="active")] | length')

    if [ "$active_count" -gt 0 ]; then
        echo "At least one MDS for $1 is active."
        exit 0
    fi

    echo "Waiting for MDS for $1 ..."
    sleep $interval
done

echo "No active MDS for $1 after $timeout seconds."
exit 1
