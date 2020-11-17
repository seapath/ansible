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

echo "Test ansible-galaxy is installed"
if ! command -v ansible-galaxy &>/dev/null ; then
    echo "Error: ansible-galaxy must be installed to continue" 1>&2
    echo "See README.adoc for instructions" 1>&2
    exit 1
fi

echo "Install role requirements.yaml"
ansible-galaxy install --roles-path="$(pwd)/roles" -r ansible-requirements.yaml
