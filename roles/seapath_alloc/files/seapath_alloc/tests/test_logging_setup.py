# Copyright (C) 2026 RTE
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import sys

import pytest

from seapath_alloc import logging_setup
from seapath_alloc.logging_setup import setup_logging


@pytest.fixture
def configure(tmp_path, monkeypatch):
    """
    Call setup_logging() against a root logger with no handlers.

    setup_logging() configures the process-wide root logger and only installs
    a handler when there is none. pytest's logging plugin attaches its own
    capture handler around every test, so the clearing has to happen here, in
    the test body, rather than in fixture setup where the plugin would undo
    it. Everything is restored afterwards.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    default_log = tmp_path / "alloc.log"

    def _configure(log_file=None, keep_handlers=(), **kwargs):
        monkeypatch.setattr(
            logging_setup, "_LOG_FILE", str(log_file or default_log)
        )
        root.handlers = list(keep_handlers)
        setup_logging(**kwargs)
        return root

    yield _configure

    for handler in root.handlers:
        handler.close()
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def test_logs_to_the_seapath_log_file(configure, tmp_path):
    root = configure()

    logging.getLogger("test").info("hello")

    assert isinstance(root.handlers[0], logging.FileHandler)
    assert "hello" in (tmp_path / "alloc.log").read_text()


def test_formats_with_level_and_logger_name(configure, tmp_path):
    configure()

    logging.getLogger("seapath_alloc.pool").warning("core 4 busy")

    assert "WARNING seapath_alloc.pool: core 4 busy" in (
        tmp_path / "alloc.log"
    ).read_text()


def test_falls_back_to_stderr_when_the_directory_is_missing(configure, tmp_path):
    root = configure(log_file=tmp_path / "absent" / "alloc.log")

    handler = root.handlers[0]
    assert type(handler) is logging.StreamHandler
    assert handler.stream is sys.stderr


def test_falls_back_to_stderr_when_the_directory_is_read_only(
    configure, monkeypatch
):
    monkeypatch.setattr(os, "access", lambda path, mode: False)

    root = configure()

    assert type(root.handlers[0]) is logging.StreamHandler


def test_falls_back_to_stderr_when_the_file_cannot_be_opened(
    configure, monkeypatch
):
    # The directory passes both checks but the open still fails, e.g. the log
    # file exists and is owned by root while the hook runs unprivileged.
    def refuse(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(logging, "FileHandler", refuse)

    root = configure()

    assert type(root.handlers[0]) is logging.StreamHandler


def test_defaults_to_info_level(configure):
    assert configure().level == logging.INFO


def test_honours_the_requested_level(configure):
    assert configure(level=logging.DEBUG).level == logging.DEBUG


def test_does_not_stack_handlers_on_a_configured_root(configure):
    existing = logging.StreamHandler(sys.stderr)

    root = configure(keep_handlers=[existing], level=logging.DEBUG)

    assert root.handlers == [existing]
    # The level is still applied, only the handler is left alone.
    assert root.level == logging.DEBUG
