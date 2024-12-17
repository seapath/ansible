#!/usr/bin/env python3

import platform
import textwrap
import subprocess
import re
import sys

def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout

def write_system_info(adoc_file):

    system_template = textwrap.dedent(
            """
            * *kernel version*: {_kernel_version_}
            * *boot options*: {_boot_options_}
            * *CPU architecture*: {_cpu_arch_}
            * *Number of physical CPUs*: {_cpu_nb_}
            * *RAM*: {_ram_} kB
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

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./system_info.py <output_file>")
        sys.exit(1)

    output_file = sys.argv[1]
    write_system_info(output_file)
