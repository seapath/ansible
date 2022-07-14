#!/usr/bin/env bash

/usr/bin/journalctl --follow | while read -r line; do
    if [[ $line == *"rcu_preempt self-detected stall on CPU"* ]]; then
        echo "date >> /log_reboot_rcu.txt"
        date >> /log_reboot_rcu.txt
        echo "systemctl stop pacemaker"
        /usr/bin/systemctl stop pacemaker
        echo "/usr/sbin/reboot"
        /usr/sbin/reboot
    fi
done

