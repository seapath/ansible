#!/bin/bash
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

# This script must be called after retrieving the sources and each change of it.
# It allows you to retrieve the dependencies required by Ansible SEAPATH.

set -e

cd "$(dirname "$(readlink -f "$0")")"

if [ $# -ne 0 ] ; then
    echo "prepare.sh take no argument" 1>&2
    exit 1
fi

echo "Test Ansible is installed"
if ! command -v ansible &>/dev/null ; then
    echo "Error: ansible must be installed to continue" 1>&2
    echo "See README.adoc for instructions" 1>&2
    exit 1
fi

echo "Test Ansible version is 2.10"
if ! ansible --version | grep -q 'ansible 2.10' ; then
    echo "Error: Installed version of ansible must match 2.10" 1>&2
    echo "See README.adoc for instructions" 1>&2
fi

echo "Test ansible-galaxy is installed"
if ! command -v ansible-galaxy &>/dev/null ; then
    echo "Error: ansible-galaxy must be installed to continue" 1>&2
    echo "See README.adoc for instructions" 1>&2
    exit 1
fi

echo "Test python3 netaddr module is installed"
if ! cat << EOF | python3 &>/dev/null
import netaddr
EOF
then
    echo "Error: python3 netaddr module must be installed" 1>&2
    echo "See README.adoc for instructions" 1>&2
    exit 1
fi

echo "Install roles in requirements.yaml"
ansible-galaxy install --roles-path="$(pwd)/roles" \
    -r ansible-requirements.yaml --force

echo "Install collections in ansible-requirements.yaml"
ansible-galaxy collection install --collections-path="$(pwd)/collections" -r \
    ansible-requirements.yaml --force

echo "Update git submodules"
git submodule update --init -f

echo "Copy ceph-ansible site.yml"
cp -vf src/ceph-ansible-site.yaml ceph-ansible/site.yml

echo "Copy ceph-group_vars"
cp -vf vars/ceph_group_vars/*.yml ceph-ansible/group_vars/

echo "Patch ceph-ansible"
find src/ceph-ansible-patches -type f -name "*.diff" -exec git -C ceph-ansible \
    apply ../{} \;
