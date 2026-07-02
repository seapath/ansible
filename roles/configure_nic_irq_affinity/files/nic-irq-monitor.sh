#!/bin/sh
# Copyright (C) 2024 Savoir-faire Linux, Inc
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0

CONF=/etc/nic-irq-affinity.conf

# Pin all IRQs for an interface to the CPU defined in the config file.
# seapath-alloc tracks NIC IRQ occupancy passively by reading
# /proc/irq/*/smp_affinity_list, so no claim registration is needed here.
#
# A value of "slot=<name>" resolves the CPU through a named seapath-alloc
# shared-core slot instead: the slot is created on first use and returned
# as-is afterwards, so the IRQs land back on the same core after a link
# bounce and stay colocated with the other actors referencing the slot.
apply() {
    iface=$1
    cpu=$(grep "^${iface} " "$CONF" | cut -d' ' -f2-)
    [ -n "$cpu" ] || return
    case "$cpu" in
        slot=*)
            name=${cpu#slot=}
            cpu=""
            command -v seapath-alloc >/dev/null 2>&1 && \
                cpu=$(seapath-alloc slot "$name")
            if [ -z "$cpu" ]; then
                logger -t nic-irq-monitor \
                    "slot $name unavailable, $iface IRQs left unpinned"
                return
            fi
            ;;
    esac
    /usr/local/bin/set_nic_irq_affinity.sh "$iface" "$cpu"
    logger -t nic-irq-monitor "pinned $iface IRQs to cpu $cpu"
}

# Apply to managed interfaces already up at startup.
while IFS= read -r line; do
    case "$line" in '#'*|'') continue ;; esac
    iface=$(printf '%s' "$line" | cut -d' ' -f1)
    ip link show "$iface" 2>/dev/null | grep -qE '[<,]UP[,>]' && apply "$iface"
done < "$CONF"

# Re-apply on link-up events (e.g. NIC reset after a transient failure).
ip monitor link | while IFS= read -r line; do
    case "$line" in
        [0-9]*:\ *:\ \<*)
            iface=$(printf '%s' "$line" | cut -d' ' -f2 | tr -d ':')
            flags=$(printf '%s' "$line" | grep -o '<[^>]*>')
            grep -q "^${iface} " "$CONF" 2>/dev/null || continue
            printf '%s' "$flags" | grep -qE '[<,]UP[,>]' && apply "$iface"
            ;;
    esac
done
