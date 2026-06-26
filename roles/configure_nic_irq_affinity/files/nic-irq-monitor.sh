#!/bin/sh
# Copyright (C) 2024 Savoir-faire Linux, Inc
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
CONF=/etc/nic-irq-affinity.conf

apply() {
    iface=$1
    cpu=$(grep "^${iface} " "$CONF" | cut -d' ' -f2-)
    [ -n "$cpu" ] || return
    /usr/local/bin/set_nic_irq_affinity.sh "$iface" "$cpu"
}

# Apply to managed interfaces already up at startup
while IFS= read -r line; do
    case "$line" in '#'*|'') continue ;; esac
    iface=$(printf '%s' "$line" | cut -d' ' -f1)
    ip link show "$iface" 2>/dev/null | grep -qE '[<,]UP[,>]' && apply "$iface"
done < "$CONF"

# Monitor link state changes
ip monitor link | while IFS= read -r line; do
    case "$line" in
        [0-9]*:\ *:\ \<*)
            iface=$(printf '%s' "$line" | cut -d' ' -f2 | tr -d ':')
            flags=$(printf '%s' "$line" | grep -o '<[^>]*>')
            printf '%s' "$flags" | grep -qE '[<,]UP[,>]' && apply "$iface"
            ;;
    esac
done
