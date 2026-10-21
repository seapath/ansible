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
COALESCE=/etc/nic-rx-usecs.conf

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
#
# A value of "slot=<name>:<cpu>" behaves like the plain static CPU list —
# the CPU comes from the config (i.e. the inventory) and is pinned
# unconditionally — but additionally informs seapath-alloc that a slot
# exists on that core, so other actors can join it by name later.
# Pinning never depends on seapath-alloc.
apply() {
    iface=$1
    cpu=$(grep "^${iface} " "$CONF" | cut -d' ' -f2-)
    [ -n "$cpu" ] || return
    case "$cpu" in
        slot=*:*)
            name=${cpu#slot=}
            cpu=${name#*:}
            name=${name%%:*}
            command -v seapath-alloc >/dev/null 2>&1 && \
                seapath-alloc slot "$name" --cpus "$cpu" >/dev/null
            ;;
        slot=*)
            logger -t nic-irq-monitor \
                "invalid '$cpu' for $iface: expected slot=<name>:<cpu>"
            return
            ;;
    esac
    set_affinity "$iface" "$cpu"
    logger -t nic-irq-monitor "pinned $iface IRQs to cpu $cpu"
}

# Set the receive interrupt coalescing of interface $1 when the config names
# it. Config format: one "<iface> <usecs>" line per interface.
#
# The driver's default may hold a frame back to batch interrupts: igb's
# rx-usecs 3, its "dynamic conservative" mode, lets an interface take one
# interrupt every 50 us or so, and the frames of a burst of Sampled Values
# after the first wait for it. rx-usecs 0 interrupts for every frame. The
# value survives a link down and up, but a driver reload puts the default
# back, after which the link comes up again and it is applied once more.
coalesce() {
    iface=$1
    usecs=$(grep "^${iface} " "$COALESCE" 2>/dev/null | cut -d' ' -f2)
    [ -n "$usecs" ] || return
    current=$(ethtool -c "$iface" 2>/dev/null | sed -n 's/^rx-usecs:[[:space:]]*//p')
    [ "$current" = "$usecs" ] && return
    if ethtool -C "$iface" rx-usecs "$usecs" 2>/dev/null; then
        logger -t nic-irq-monitor "set $iface rx-usecs to $usecs (was $current)"
    else
        logger -t nic-irq-monitor "could not set $iface rx-usecs to $usecs"
    fi
}

# The interfaces either config names.
managed() {
    cat "$CONF" "$COALESCE" 2>/dev/null | grep -v -e '^#' -e '^$' | cut -d' ' -f1 | sort -u
}

# Startup pass: apply to managed interfaces that are already up, so a manual
# service restart re-pins them without waiting for the next link event.
for iface in $(managed); do
    ip link show "$iface" 2>/dev/null | grep -qE '[<,]UP[,>]' && { apply "$iface"; coalesce "$iface"; }
done

# Event loop: re-apply on every link UP event. ip monitor link blocks on the
# netlink socket and only emits a line when the link state actually changes,
# so this consumes no CPU at rest. Lines look like:
#   3: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
ip monitor link | while IFS= read -r line; do
    case "$line" in
        [0-9]*:\ *:\ \<*)
            iface=$(printf '%s' "$line" | cut -d' ' -f2 | tr -d ':')
            flags=$(printf '%s' "$line" | grep -o '<[^>]*>')
            cat "$CONF" "$COALESCE" 2>/dev/null | grep -q "^${iface} " || continue
            printf '%s' "$flags" | grep -qE '[<,]UP[,>]' && { apply "$iface"; coalesce "$iface"; }
            ;;
    esac
done
