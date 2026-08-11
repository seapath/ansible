# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""
Helpers shared by the unit tests.

The Python in this repository is not an installable package: it is a set of
standalone scripts deployed as role ``files/`` payloads, plus one Ansible
module and one CI helper. The tests therefore import them by path.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script(relpath, name=None):
    """
    Import a standalone script by its path relative to the repository root.

    Every script under test guards its entry point with ``if __name__ ==
    "__main__"``, so importing one runs its definitions and nothing else.
    """
    path = REPO_ROOT / relpath
    name = name or path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Registering before exec_module keeps the module importable from itself,
    # which dataclasses and pickle rely on.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
