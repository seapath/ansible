# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import sys

_LOG_FILE = "/var/log/seapath/alloc.log"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO):
    """
    Configure the root logger.

    Writes to /var/log/seapath/alloc.log when the directory exists and is
    writable; falls back to stderr otherwise (e.g. during tests or on hosts
    where the Ansible role hasn't run yet).
    """
    log_dir = os.path.dirname(_LOG_FILE)
    handler = None

    if os.path.isdir(log_dir) and os.access(log_dir, os.W_OK):
        try:
            handler = logging.FileHandler(_LOG_FILE)
        except OSError:
            pass

    if handler is None:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
