"""Tests for gui/crash_handler.py — defensive wrappers must catch
BaseException (including KeyboardInterrupt + SystemExit) so the crash
handler itself never crashes the process."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _never_open_the_modal(monkeypatch):
    """Stop _exception_hook from opening its blocking QMessageBox.

    Its last step is:

        if QApplication.instance() is not None:
            QMessageBox.critical(None, "Unhandled exception", ...)

    QMessageBox.critical is MODAL -- it blocks until someone clicks a button,
    which never happens in a headless run. These tests call _exception_hook
    directly, so whether they finish depended entirely on whether some
    earlier test file had left a QApplication alive.

    For a long time nothing alphabetically before "test_crash_handler"
    created one, so this passed by accident. Adding
    tests/test_basic_pro_disclosure.py ("b" < "c") put a QApplication in
    place first and the whole suite wedged here -- hanging, not failing,
    which is far harder to diagnose.

    Patching the name as imported INTO crash_handler (not QtWidgets) keeps
    this independent of test ordering and of whether Qt is initialised.
    """
    monkeypatch.setattr(
        "gui.crash_handler.QMessageBox.critical",
        lambda *a, **k: None,
        raising=False,
    )


def test_exception_hook_swallows_keyboardinterrupt_from_traceback_print(monkeypatch):
    """If traceback.print_exception raises KeyboardInterrupt (Python 3.13
    formatter bug observed when SIGINT arrives mid-format), the crash
    handler must NOT let it propagate."""
    from gui import crash_handler

    def _boom(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(crash_handler.traceback, "print_exception", _boom)
    # Also stub out the log file write so it doesn't pollute disk
    monkeypatch.setattr(crash_handler, "_LOG_DIR", crash_handler._LOG_DIR)

    # If this raises, the test fails — that's the regression we're guarding.
    crash_handler._exception_hook(ValueError, ValueError("test"), None)


def test_exception_hook_swallows_systemexit_from_log_write(monkeypatch, tmp_path):
    """If the log file write itself raises SystemExit (extreme edge case),
    the handler still doesn't kill the process."""
    from gui import crash_handler

    def _boom_open(*args, **kwargs):
        raise SystemExit(2)

    monkeypatch.setattr("builtins.open", _boom_open)
    # Should not raise SystemExit
    crash_handler._exception_hook(ValueError, ValueError("test"), None)


def test_qt_message_handler_swallows_baseexception(monkeypatch):
    """Same guarantee for the Qt message handler."""
    from gui import crash_handler
    from PyQt6.QtCore import QtMsgType

    def _boom_open(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("builtins.open", _boom_open)
    crash_handler._qt_message_handler(QtMsgType.QtWarningMsg, None, "test message")
