#!/bin/sh
# Copyright (C) 2024 Savoir-faire Linux, Inc
# Copyright (C) 2024 RTE
# SPDX-License-Identifier: Apache-2.0
#
# NIC IRQ affinity monitor.
#
# The kernel resets /proc/irq/<N>/smp_affinity_list to the default mask every
# time request_irq() runs, which happens in the driver's ndo_open() each time
# an interface is brought up (boot bring-up, admin down/up, driver reload,
# ethtool channel/ring change). A one-shot applied at boot is therefore racy:
# if it runs before the interface is first opened, its writes are discarded.
#
# This daemon instead applies the configured affinity on the actual link UP
# event, delivered by the kernel via netlink (ip monitor link) after ndo_open()
# has completed and the IRQs are registered. It is independent of the network
# manager in use (networkd, NetworkManager, ifupdown all produce the same
# RTM_NEWLINK events).

CONF=/etc/nic-irq-affinity.conf

# Pin every IRQ owned by interface $1 to CPU list $2.
#
# The IRQ numbers are taken from sysfs rather than parsed out of the IRQ action
# names under /proc/irq/. Those names are driver-specific: some start with the
# interface name (eth0-TxRx-0), some prefix it with other information, and some
# (e.g. mlx5) do not contain it at all, so name matching is both fragile and
# prone to collisions (eth1 vs eth10). /sys/class/net/<iface>/device exposes the
# IRQs the NIC's PCI device actually owns: msi_irqs/ lists the MSI/MSI-X vectors
# (the per-queue IRQs on modern NICs), with the legacy single "irq" file as a
# fallback. Writing the CPU list to /proc/irq/<N>/smp_affinity_list steers each
# IRQ to the given CPUs. Kept as a function (rather than a separate executable)
# so nothing outside this daemon can invoke it directly.
set_affinity() {
    nic=$1
    cpu=$2
    dev="/sys/class/net/${nic}/device"
    if [ -d "${dev}/msi_irqs" ]; then
        for irq in "${dev}"/msi_irqs/*; do
            irqnum=$(basename "$irq")
            [ -w "/proc/irq/${irqnum}/smp_affinity_list" ] || continue
            echo "$cpu" > "/proc/irq/${irqnum}/smp_affinity_list" 2>/dev/null || true
        done
    elif [ -r "${dev}/irq" ]; then
        irqnum=$(cat "${dev}/irq")
        [ -w "/proc/irq/${irqnum}/smp_affinity_list" ] &&
            { echo "$cpu" > "/proc/irq/${irqnum}/smp_affinity_list" 2>/dev/null || true; }
    fi
}

# Look up the interface in the config and apply its affinity if it has an entry.
# Config format: one "<iface> <cpulist>" line per interface; '#' and blank
# lines are ignored.
#
# seapath-alloc tracks NIC IRQ occupancy passively by reading
# /proc/irq/*/smp_affinity_list, so no claim registration is needed here.
apply() {
    iface=$1
    cpu=$(grep "^${iface} " "$CONF" | cut -d' ' -f2-)
    [ -n "$cpu" ] || return
    set_affinity "$iface" "$cpu"
    logger -t nic-irq-monitor "pinned $iface IRQs to cpu $cpu"
}

# Startup pass: apply to managed interfaces that are already up, so a manual
# service restart re-pins them without waiting for the next link event.
while IFS= read -r line; do
    case "$line" in '#'*|'') continue ;; esac
    iface=$(printf '%s' "$line" | cut -d' ' -f1)
    ip link show "$iface" 2>/dev/null | grep -qE '[<,]UP[,>]' && apply "$iface"
done < "$CONF"

# Event loop: re-apply on every link UP event. ip monitor link blocks on the
# netlink socket and only emits a line when the link state actually changes,
# so this consumes no CPU at rest. Lines look like:
#   3: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
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
