"""
Shared worker lifecycle utilities for GUI tabs.

Two distinct patterns:

cancel_worker()  — mid-operation replacement: block signals so stale results
                   are silently discarded. Does NOT wait. Safe to call from
                   the GUI thread at any time.

stop_worker()    — app-exit teardown: block signals, ask the thread to quit
                   (for event-loop threads), then wait up to `timeout_ms` for
                   natural completion, finally terminate() if still alive.
                   Qt 6.10 made it fatal to destroy a QThread while it is
                   still running, so cleanup() methods MUST call this instead
                   of cancel_worker().
"""


# Cancelled workers whose thread is still running. Callers drop their own
# reference right after cancel_worker (`self._x_worker = None`); if that was
# the last one, Python destroyed the QThread mid-run and Qt 6.10 aborts the
# whole app ("QThread: Destroyed while thread is still running" -- the
# 2026-10-01 Dashboard crash on cold starts). Holding them here until their
# thread ends makes dropping the caller's reference safe.
_RETIRED: list = []


def prune_retired():
    """Release parked workers whose thread has ended (safe to destroy now)."""
    alive = []
    for w in _RETIRED:
        try:
            if w.isRunning():
                alive.append(w)
        except RuntimeError:
            pass
    _RETIRED[:] = alive


def stop_retired(timeout_ms: int = 2000):
    """App exit: wait for (or stop) every parked worker before teardown."""
    for w in list(_RETIRED):
        stop_worker(w, timeout_ms)
    prune_retired()


def cancel_worker(worker):
    """
    Safely cancel a running QThread worker by blocking its signals.

    Guards against RuntimeError when the underlying C++ object has already
    been freed by deleteLater (e.g. auto-refresh completes before user
    clicks Refresh, leaving the reference pointing at a dead wrapper).

    Does NOT call wait() — workers with no event loop would block the GUI.
    Signal-blocking + generation counters are sufficient to discard stale results.
    A still-running worker is parked in _RETIRED until its thread ends, so the
    caller may drop its own reference immediately.
    """
    prune_retired()
    if worker is not None:
        try:
            worker.blockSignals(True)
            if worker.isRunning():
                _RETIRED.append(worker)
        except RuntimeError:
            pass


def stop_worker(worker, timeout_ms: int = 2000):
    """
    Fully stop a QThread worker at app-exit time.

    Qt 6.10 aborts the process if a QThread object is destroyed while its
    thread is still running.  This function guarantees the thread has stopped
    before the caller's reference is released:

      1. blockSignals — prevents stale callbacks from firing during teardown.
      2. quit()       — posts a quit event (effective for event-loop threads).
      3. wait()       — waits up to `timeout_ms` ms for natural exit.
      4. terminate()  — force-kills the thread if still alive after wait().

    For DataLoadWorker (no event loop), quit() is a no-op but wait() works
    because the thread exits as soon as run() returns, which is near-instant
    for a SQL query.
    """
    if worker is None:
        return
    try:
        worker.blockSignals(True)
        if worker.isRunning():
            worker.quit()
            if not worker.wait(timeout_ms):
                worker.terminate()
                worker.wait(500)
    except RuntimeError:
        # C++ object already freed by deleteLater — nothing to do
        pass


def cleanup_workers(*workers, timeout_ms: int = 2000):
    """Stop multiple workers at app-exit time. Returns None for easy assignment."""
    for w in workers:
        stop_worker(w, timeout_ms)
    return None
