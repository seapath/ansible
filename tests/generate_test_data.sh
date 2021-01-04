# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

# The script will generate all test data in testdata directory
if [ $# -ne 0 ] ; then
    echo "The script doesn't take any parameters"
    exit 1
fi

cd "$(dirname "$(readlink -f \\"$0\\")")"
rm -rf testdata
mkdir testdata
qemu-img create -f qcow2 testdata/disk.qcow2 5M
fallocate -l 5M testdata/disk
wget "https://cloud-images.ubuntu.com/bionic/current/bionic-server-cloudimg-amd64.img" -O testdata/os.qcow2
