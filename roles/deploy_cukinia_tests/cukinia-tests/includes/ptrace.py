# Copyright (C) 2023, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# Use to generate ptrace syscall

import ctypes

# Define constants for the ptrace system call
PTRACE_SYSTEM_CALL_NUMBER = 101
PTRACE_ATTACH = 16
PTRACE_CONT = 7

# Load the libc library
libc = ctypes.CDLL("libc.so.6")

# Call the ptrace system call
pid = 0
result = libc.syscall(PTRACE_SYSTEM_CALL_NUMBER, PTRACE_ATTACH, pid, 0, 0)

# Check the result of the system call
if result == 0:
    print("ptrace succeeded")

    # Send a continue signal to the traced process
    result = libc.syscall(PTRACE_SYSTEM_CALL_NUMBER, PTRACE_CONT, pid, 0, 0)

    # Check the result of the system call
    if result == 0:
        print("ptrace continue succeeded")
    else:
        print("ptrace continue failed")
else:
    print("ptrace failed")
