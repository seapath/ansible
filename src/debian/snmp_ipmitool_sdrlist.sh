#!/bin/bash

/usr/bin/ipmitool sdr list | sed -e "s/ *| */;/g"
