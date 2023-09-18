#!/bin/bash

/usr/bin/ipmitool sensor | sed -e "s/ *| */;/g"
