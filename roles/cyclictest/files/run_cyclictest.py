#!/usr/bin/env python3

import subprocess
import sys
import argparse

parser = argparse.ArgumentParser(description="Run cyclictest command.")
parser.add_argument('output_file', type=str, help='File to output the result.')
parser.add_argument('-d', '--duration', type=int, help='Test duration in seconds.', default=20)
parser.add_argument('-p', '--priority', type=int, help='Priority of the threads.', default=90)
parser.add_argument('-a', '--affinity', type=str, help='CPU affinity', nargs='?', const="", default="smp")
args = parser.parse_args()

interval = 200  # In microseconds
cycles = (args.duration * 10**6) // interval
cpu_arg = "-S"
if args.affinity != "smp":
    cpu_arg = f"-a {args.affinity} -t"

cyclic_test_cmd = f"cyclictest -l{cycles} -m {cpu_arg} -p{args.priority} -i{interval} -h400 -q"
print(f"Will run command: {cyclic_test_cmd}")

result = subprocess.run(cyclic_test_cmd.split(), capture_output=True, text=True)

with open(args.output_file, 'w') as f:
    f.write(cyclic_test_cmd)
    f.write(result.stdout)
