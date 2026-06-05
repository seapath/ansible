# Copyright (C) 2023, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# Use to generate ioperm syscall on target

import ctypes

# Define constants for the ioperm system call
IOPERM_SYSTEM_CALL_NUMBER = 173
START_IO_PORT = 0x8000
NUM_IO_PORTS = 16
IO_PERM_ENABLE = 1

# Load the libc library
libc = ctypes.CDLL("libc.so.6")

# Call the ioperm system call
result = libc.syscall(
    IOPERM_SYSTEM_CALL_NUMBER, START_IO_PORT, NUM_IO_PORTS, IO_PERM_ENABLE
)

# Check the result of the system call
if result == 0:
    print("ioperm succeeded")
else:
    print("ioperm failed")
