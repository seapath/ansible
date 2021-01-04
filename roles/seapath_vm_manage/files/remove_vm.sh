#!/bin/bash
# Copyright (C) 2020, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

# Remove a VM

set -e
resource="$1"

tmp_cib=$(mktemp)

crm configure show "${resource}" >"${tmp_cib}"

if ! grep -q 'force_stop=true' "${tmp_cib}" ; then
    if grep -q "force_stop=false" "${tmp_cib}" ; then
        sed 's/force_stop=false/force_stop=true/' -i "${tmp_cib}"
    else
        sed  '2s/ \\$/ force_stop=true \\/' -i "${tmp_cib}"
    fi
    crm configure load update "${tmp_cib}"
fi
rm -f "${tmp_cib}"

crm resource stop "${resource}"
timer=0
while crm resource status "$resource" | grep -q "is running" ; do
    # Wait until 5s
    if [ "$timer" -gt 5000 ] ; then
        echo "Error the resource do not stop on time !" 1>&2
        exit 1
    fi
    sleep 0.5
    timer=$(( timer + 500 ))
done
crm configure delete "${resource}"
