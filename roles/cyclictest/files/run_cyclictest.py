#!/usr/bin/env python3

import subprocess
import sys
import argparse

parser = argparse.ArgumentParser(description="Run cyclictest command.")
parser.add_argument('output_file', type=str, help='File to output the result.')
parser.add_argument('-d', '--duration', type=int, help='Test duration in seconds.', default=20)
args = parser.parse_args()

interval = 200  # In microseconds
cycles = (args.duration * 10**6) // interval

cyclic_test_cmd = f"cyclictest -l{cycles} -m -Sp90 -i{interval} -h400 -q"
print(f"Will run command: {cyclic_test_cmd}")

result = subprocess.run(cyclic_test_cmd.split(), capture_output=True, text=True)

with open(args.output_file, 'w') as f:
    f.write(result.stdout)
