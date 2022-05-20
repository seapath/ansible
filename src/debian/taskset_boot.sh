#!/bin/bash

/usr/bin/taskset -acp 0,12 2
/usr/bin/taskset -acp 0,12 $(pgrep rcu_preempt)
