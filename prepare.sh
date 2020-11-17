#!/bin/bash

set -e

cd "$(dirname "$(readlink -f \\"$0\\")")"

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

echo "Test Ansible version is 2.9"
if ! ansible --version | grep -q 'ansible 2.9' ; then
    echo "Error: Installed version of ansible must match 2.9" 1>&2
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

echo "Install role requirements.yaml"
ansible-galaxy install --roles-path="$(pwd)/roles" -r ansible-requirements.yaml
