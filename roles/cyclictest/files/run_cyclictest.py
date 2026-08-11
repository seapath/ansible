#!/usr/bin/env python3

import subprocess
import argparse

INTERVAL = 200  # In microseconds


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run cyclictest command.")
    parser.add_argument('output_file', type=str, help='File to output the result.')
    parser.add_argument('-d', '--duration', type=int, help='Test duration in seconds.', default=20)
    parser.add_argument('-p', '--priority', type=int, help='Priority of the threads.', default=90)
    parser.add_argument('-a', '--affinity', type=str, help='CPU affinity', nargs='?', const="", default="smp")
    return parser.parse_args(argv)


def build_command(args):
    cycles = (args.duration * 10**6) // INTERVAL
    cpu_arg = "-S"
    if args.affinity != "smp":
        cpu_arg = f"-a {args.affinity} -t"

    return f"cyclictest -l{cycles} -m {cpu_arg} -p{args.priority} -i{INTERVAL} -h400 -q"


def main(argv=None):
    args = parse_args(argv)
    cyclic_test_cmd = build_command(args)
    print(f"Will run command: {cyclic_test_cmd}")

    result = subprocess.run(cyclic_test_cmd.split(), capture_output=True, text=True)

    with open(args.output_file, 'w') as f:
        f.write(cyclic_test_cmd)
        f.write(result.stdout)


if __name__ == "__main__":
    main()
