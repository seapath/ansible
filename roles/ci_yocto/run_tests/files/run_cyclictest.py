#!/usr/bin/env python3

import subprocess
import sys
import argparse

parser = argparse.ArgumentParser(description="Run cyclictest command.")
parser.add_argument('output_file', type=str, help='File to output the result.')
args = parser.parse_args()

cyclic_test_cmd = "cyclictest -l100000 -m -Sp90 -i200 -h400 -q"
result = subprocess.run(cyclic_test_cmd.split(), capture_output=True, text=True)

with open(args.output_file, 'w') as f:
    f.write(result.stdout)
