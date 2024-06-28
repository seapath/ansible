#!/usr/bin/env python3

import subprocess
import matplotlib.pyplot as plt

cyclic_test_cmd = "cyclictest -l100000000 -m -Sp90 -i200 -h400 -q"
result = subprocess.run(cyclic_test_cmd.split(), capture_output=True, text=True)

latencies = []
for line in result.stdout.split('\n'):
    if "us" in line: 
        parts = line.split()
        latency = int(parts[-2]) 
        latencies.append(latency)

plt.figure(figsize=(10, 6))
plt.plot(latencies)
plt.xlabel('Test Number')
plt.ylabel('Latency (us)')
plt.title('Cyclictest Latency Results')
plt.savefig('cyclictest_results.png')
