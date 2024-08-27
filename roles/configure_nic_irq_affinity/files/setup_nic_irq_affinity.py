#!/usr/bin/env python3
# Copyright (C) 2024 Savoir-faire Linux, Inc
# SPDX-License-Identifier: Apache-2.0

# This script is used to set the IRQs affinity of the NICs to the CPUs
# in order to optimize the performance of the network interface.
# This takes takes a list of NICs and a list of CPUs and sets the IRQs

import argparse
import os
import sys


def args_parser():
    parser = argparse.ArgumentParser(
        description="Set the IRQs affinity of the NICs to the CPUs"
    )
    parser.add_argument(
        "--nic",
        action="append",
        help="NICs to set the IRQs affinity",
        required=True,
        type=str,
    )
    parser.add_argument(
        "--cpu",
        help="CPUs to set the IRQs affinity (in the format 0-3,4-7,8-11,12-15)",
        action="append",
        type=str,
        required=True,
    )
    return parser.parse_args()


def get_irqs(nic):
    irqs = []
    # Iterate over the files in /proc/irq
    for irq in os.listdir("/proc/irq"):
        # Check if the file is a directory
        if os.path.isdir("/proc/irq/" + irq):
            # Check if there is a directory which begins with the NIC name
            # Iterate over the files in /proc/irq/irq
            for irq_file in os.listdir("/proc/irq/" + irq):
                # Check if the file is a directory
                if os.path.isdir("/proc/irq/" + irq + "/" + irq_file):
                    # Check if there is a directory which begins with the NIC name
                    if irq_file.startswith(nic):
                        # Append the IRQ number to the list
                        irqs.append(irq)
    return irqs


def set_irqs_affinity(irqs, cpus):
    for irq in irqs:
        # Set the affinity of the IRQ to the CPUs
        with open("/proc/irq/" + irq + "/smp_affinity_list", "w") as f:
            f.write(cpus)


def main():
    args = args_parser()
    i = 0
    if len(args.nic) != len(args.cpu):
        print("The number of NICs and CPUs must be the same", file=sys.stderr)
        sys.exit(1)
    for nic in args.nic:
        irqs = get_irqs(nic)
        set_irqs_affinity(irqs, args.cpu[i])
        i += 1


if __name__ == "__main__":
    main()
