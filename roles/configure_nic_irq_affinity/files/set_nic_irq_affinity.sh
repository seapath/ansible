#!/bin/sh
# Copyright (C) 2024 Savoir-faire Linux, Inc
# SPDX-License-Identifier: Apache-2.0
NIC=$1
CPU=$2

for irq_path in /proc/irq/*/; do
    for entry in "$irq_path"*/; do
        [ -d "$entry" ] || continue
        case "$(basename "$entry")" in
            "${NIC}"*) echo "$CPU" > "${irq_path}smp_affinity_list" ;;
        esac
    done
done
