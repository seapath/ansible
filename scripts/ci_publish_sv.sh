# Copyright (C) 2024 Savoir-faire Linux, Inc
# SPDX-License-Identifier: Apache-2.0

#!/bin/bash
set -x

# First parameter : interface
# Second parameter : root directory
# Third parameter : pcap file

CMD_RUNNER="bittwist -i $1 $2/pcaps/$3"

$CMD_RUNNER &
PID_RUNNER=$!

wait $PID_RUNNER
exit 0
