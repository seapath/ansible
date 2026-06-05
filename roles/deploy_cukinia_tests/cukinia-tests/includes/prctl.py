# Copyright (C) 2023, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# Use to generate prctl syscall

import ctypes

# Define constants for the prctl system call
PRCTL_SYSTEM_CALL_NUMBER = 157
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2

# Load the libc library
libc = ctypes.CDLL("libc.so.6")

# Call the prctl system call
result = libc.syscall(
    PRCTL_SYSTEM_CALL_NUMBER, PR_SET_SECCOMP, SECCOMP_MODE_FILTER, 0, 0, 0
)

# Check the result of the system call
if result == 0:
    print("prctl succeeded")
else:
    print("prctl failed")
