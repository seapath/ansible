#!/usr/bin/env bash

/usr/bin/journalctl --follow | while read -r line; do
    if [[ $line == *"rcu_preempt self-detected stall on CPU"* ]]; then
        echo "hard: sleep 3min"
        sleep 180
        echo "hard reboot"
        echo s > /proc/sysrq-trigger
        echo b > /proc/sysrq-trigger
    fi
done
