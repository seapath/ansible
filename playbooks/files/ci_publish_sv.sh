# Copyright (C) 2024 Savoir-faire Linux, Inc
# SPDX-License-Identifier: Apache-2.0

#!/bin/bash
set -x

# First parameter : pcap file
# Second parameter : root directory

CMD_RUNNER="bittwist -i eno1 $2/pcaps/$1"

CMD_DUMP="tcpdump -w $2/results/result-$(date +%s).pcap"

$CMD_DUMP &
PID_DUMP=$!

$CMD_RUNNER &
PID_RUNNER=$!

wait $PID_RUNNER
kill -2 $PID_DUMP

wait $PID_DUMP

exit 0
