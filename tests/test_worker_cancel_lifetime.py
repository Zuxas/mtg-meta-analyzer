"""A cancelled QThread must stay referenced until its thread ends.

Found 2026-10-01 (app aborted 10-30 s after launch, `QThread: Destroyed while thread '' is still
running` in logs/qt_msgs_*.log): `cancel_worker` blocked the worker's signals and every caller
then dropped its reference (`self._x_worker = None`) -- when that was the last reference, Python
destroyed the C++ QThread mid-run and Qt 6.10 aborts the process. It fired when a Dashboard
reload landed while a previous load was still running (slow cold-start queries)."""
import gc
import threading
import weakref

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from gui import worker_utils


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class _Slow(QThread):
    def __init__(self, gate):
        super().__init__()
        self.gate = gate

    def run(self):
        self.gate.wait(5)


def test_cancelled_running_worker_is_kept_alive_until_it_finishes(app):
    gate = threading.Event()
    w = _Slow(gate)
    w.start()
    ref = weakref.ref(w)
    worker_utils.cancel_worker(w)
    del w                                       # the caller drops its reference, as every tab does
    gc.collect()
    assert ref() is not None and ref().isRunning()   # still held: destroying it now would abort Qt
    gate.set()
    assert ref().wait(3000)
    worker_utils.prune_retired()
    gc.collect()
    assert ref() is None                        # released once the thread has ended


def test_cancelling_a_finished_or_dead_worker_is_harmless(app):
    worker_utils.cancel_worker(None)
    gate = threading.Event()
    gate.set()
    w = _Slow(gate)
    w.start()
    assert w.wait(3000)
    worker_utils.cancel_worker(w)
    assert w not in worker_utils._RETIRED       # not running: nothing to hold


def test_stop_retired_waits_for_parked_workers(app):
    gate = threading.Event()
    w = _Slow(gate)
    w.start()
    worker_utils.cancel_worker(w)
    threading.Timer(0.2, gate.set).start()
    worker_utils.stop_retired(timeout_ms=3000)
    assert not w.isRunning() and not worker_utils._RETIRED
