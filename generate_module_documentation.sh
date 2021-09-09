#!/usr/bin/env sh
# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0


set -e
cd module_documentation_sources
python3 plugin_formatter.py -M ../library -T templates/ -o source -A 2.9 -P module
sphinx-build source ../module_documentation
