#!/usr/bin/env python3
#
# Copyright (C) 2025 Florent CARLI
# SPDX-License-Identifier: GPL-3.0-only

import sys
import os
import time
import xml.etree.ElementTree as ET
import subprocess

logfile = "/var/log/libvirt/hook.log"
log_dir = os.path.dirname(logfile)
os.makedirs(log_dir, exist_ok=True)
sys.stdout = open(logfile, "a")
sys.stderr = sys.stdout

def usage():
    print("Usage: configure_guest.py <vm_name> <vm_action>")
    print("  vm_name   : name of the guest VM")
    print("  vm_action : one of the following:")
    print("              started       - run commands for real")
    print("              started-dry   - dry-run, print commands only")
    print("              any other     - do nothing and exit")
    sys.exit(0)

def parse_xml(guest_name):
    filename = f"/etc/pacemaker/{guest_name}.xml"
    try:
        tree = ET.parse(filename)
        root = tree.getroot()
        return root
    except (FileNotFoundError, ET.ParseError) as e:
        print(f"Error reading XML for {guest_name}: {e}")
        sys.exit(0)

def run_ethtool_commands(root, dry_run):
    for interface in root.findall(".//interface"):
        target = interface.find("target")
        if target is not None and "dev" in target.attrib:
            dev = target.attrib["dev"]
            cmd = ["/sbin/ethtool", "-s", dev, "autoneg", "off", "speed", "1000", "duplex", "full"]
            if dry_run:
                print(f"Dry run: {' '.join(cmd)}")
            else:
                print(f"Running: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)

def is_realtime_guest(root):
    return root.find(".//cputune/vcpusched") is not None

def find_qemu_pid(guest_name):
    try:
        output = subprocess.check_output(["ps", "axo", "pid,command"], text=True)
        for line in output.splitlines():
            if "qemu-" in line and f"guest={guest_name}," in line:
                return int(line.strip().split()[0])
    except subprocess.CalledProcessError:
        pass
    return None

def find_qemu_pid_with_retry(guest_name, retries=10, delay=1):
    count = 0
    while count < retries:
        pid = find_qemu_pid(guest_name)
        if pid:
            return pid
        time.sleep(delay)
        count += 1
    print("No qemu process found")
    sys.exit(0)

def find_vhost_pids(qemu_pid, retries=10, delay=1):
    """
    Finds vhost worker IDs for a given QEMU process.
    Works with both:
      - Old kernels: vhost is its own kernel thread process ([vhost-<pid>])
      - New kernels: vhost threads live inside the QEMU process
    Returns: list of PIDs (old kernel) or TIDs (new kernel)
    """
    for _ in range(retries):
        # --- Try old behavior first ---
        print("find_vhost_pids: Try old behavior first with qemu_pid=" + str(qemu_pid))
        pids = []
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                try:
                    with open(f"/proc/{pid}/comm") as f:
                        if f.read().strip() == f"vhost-{qemu_pid}":
                            pids.append(int(pid))
                except FileNotFoundError:
                    continue
        if pids:
            print(f"Found old-kernel vhost PIDs via /proc: {pids}")
            return pids

        # --- Try new behavior ---
        print("find_vhost_pids: Try new behavior")
        task_dir = f"/proc/{qemu_pid}/task"
        if os.path.isdir(task_dir):
            vhost_tids = []
            for tid in os.listdir(task_dir):
                try:
                    with open(f"{task_dir}/{tid}/comm") as f:
                        if f.read().strip() == f"vhost-{qemu_pid}":
                            vhost_tids.append(int(tid))
                except FileNotFoundError:
                    # Thread might have exited between listing and reading
                    continue
            if vhost_tids:
                print(f"Found new-kernel vhost PIDs via /proc: {vhost_tids}")
                return vhost_tids

        time.sleep(delay)

    return []

def get_affinity(pid):
    try:
        output = subprocess.check_output(["taskset", "-p", str(pid)], text=True)
        return output.strip().split(":")[1].strip()
    except subprocess.CalledProcessError:
        return None

def apply_realtime_settings(pid_list, affinity, dry_run):
    for pid in pid_list:
        if dry_run:
            print(f"Dry run: taskset -p {affinity} {pid}")
            print(f"Dry run: chrt -p 1 {pid}")
        else:
            subprocess.run(["taskset", "-p", affinity, str(pid)], check=True)
            subprocess.run(["chrt", "-p", "1", str(pid)], check=True)

def handle_kvm_pit(qemu_pid, affinity, dry_run):
    try:
        output = subprocess.check_output(["pgrep", f"kvm-pit/{qemu_pid}"], text=True)
        for line in output.splitlines():
            pid = int(line.strip())
            if dry_run:
                print(f"Dry run: taskset -p {affinity} {pid}")
                print(f"Dry run: chrt -p 1 {pid}")
            else:
                print(f"taskset -p {affinity} {pid}")
                print(f"chrt -p 1 {pid}")
                subprocess.run(["taskset", "-p", affinity, str(pid)], check=True)
                subprocess.run(["chrt", "-p", "1", str(pid)], check=True)
    except subprocess.CalledProcessError:
        pass

def main():
    print(f"Script called with: {' '.join(sys.argv)}")
    if len(sys.argv) < 3:
        usage()

    guest_name = sys.argv[1]
    vm_action = sys.argv[2]

    if vm_action == "started":
        dry_run = False
    elif vm_action == "started-dry":
        dry_run = True
    else:
        # For other actions do nothing
        sys.exit(0)

    root = parse_xml(guest_name)

    if is_realtime_guest(root):
        print(f"\nGuest {guest_name} is marked as realtime.")
        qemu_pid = find_qemu_pid_with_retry(guest_name)
        print(f"QEMU PID: {qemu_pid}")

        vhost_pids = find_vhost_pids(qemu_pid)
        if not vhost_pids:
            print("No vhost-* threads found for QEMU.")
            sys.exit(1)

        affinity = get_affinity(qemu_pid)
        if not affinity:
            print("Could not get CPU affinity.")
            sys.exit(1)

        apply_realtime_settings(vhost_pids, affinity, dry_run)
        handle_kvm_pit(qemu_pid, affinity, dry_run)
    else:
        print(f"\nGuest {guest_name} is not realtime. Skipping vhost thread tuning.")

    run_ethtool_commands(root, dry_run)

if __name__ == "__main__":
    main()
