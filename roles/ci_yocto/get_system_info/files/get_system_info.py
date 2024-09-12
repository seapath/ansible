#!/usr/bin/env python3

import platform
import textwrap
import subprocess
import re
import sys

def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout

def get_network_interfaces():
    result = run_command(['ip', 'link', 'show'])
    interfaces = []
    for line in result.split('\n'):
        if ': ' in line:
            interface = line.split(': ')[1].split('@')[0]
            interfaces.append(interface)
    return interfaces

def get_interface_capabilities(interface):
    result = run_command(['ethtool', interface])
    capabilities = {}
    for line in result.split('\n'):
        if 'Speed:' in line:
            capabilities['Speed'] = line.split(': ')[1].strip()
        if 'Duplex:' in line:
            capabilities['Duplex'] = line.split(': ')[1].strip()
        if 'Auto-negotiation:' in line:
            capabilities['Auto-negotiation'] = line.split(': ')[1].strip()
    return capabilities

def get_hardware_ptp(interface):
    result = run_command(['ethtool', '-T', interface])
    ptp_info = 'Not supported'
    for line in result.split('\n'):
        if 'PTP Hardware Clock' in line and not 'none' in line:
            ptp_info = 'Supported'
            break
    return ptp_info

def write_system_info(adoc_file):

    system_template = textwrap.dedent(
            """
            * *kernel version*: {_kernel_version_}
            * *boot options*: {_boot_options_}
            * *CPU architecture*: {_cpu_arch_}
            * *Number of physical CPUs*: {_cpu_nb_} 
            * *RAM*: {_ram_} kB
            * *Network interfaces*: 
            """
            )

    network_template = textwrap.dedent(
            """
            ** *Interface Name*: {_net_name_}
            ** *Capabilities*:
                *** _Speed_: {_speed_}
                *** _Duplex_: {_duplex_}
                *** _Auto-negotiation_: {_autoneg_}
                *** _Hardware_ _PTP_: {_ptp_}
            """
            )
    with open(output_file, "w", encoding="utf-8") as adoc_file:
        adoc_file.write(
                system_template.format(
                    _kernel_version_ = f"{platform.platform()} {platform.version()}",
                    _boot_options_ = run_command(['cat', '/proc/cmdline']),
                    _cpu_arch_ = platform.machine(),
                     _cpu_nb_ = run_command(['bash', '-c', 'cat /proc/cpuinfo | grep "cpu cores" | head -n 1 | grep -o "[0-9]\+"']),
                    _ram_ = int(re.search(r'MemTotal:\s+(\d+)',run_command(['cat', '/proc/meminfo']).strip()).group(1))
            )
    )
    
        interfaces = get_network_interfaces()
        for interface in interfaces:
            capabilities = get_interface_capabilities(interface)
            ptp_support = get_hardware_ptp(interface)
            adoc_file.write(
                network_template.format(
                    _net_name_=interface,
                    _speed_=capabilities.get('Speed', 'Unknown'),
                    _duplex_=capabilities.get('Duplex', 'Unknown'),
                    _autoneg_=capabilities.get('Auto-negotiation', 'Unknown'),
                    _ptp_=ptp_support
                )
            )

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./system_info.py <output_file>")
        sys.exit(1)

    output_file = sys.argv[1]
    write_system_info(output_file)
