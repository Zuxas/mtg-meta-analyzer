"""
Shared worker lifecycle utilities for GUI tabs.

All QThread workers use the same cancel/cleanup pattern:
block signals to discard stale results, guard against RuntimeError
when the C++ QThread has already been freed by deleteLater.
"""


def cancel_worker(worker):
    """
    Safely cancel a running QThread worker by blocking its signals.

    Guards against RuntimeError when the underlying C++ object has already
    been freed by deleteLater (e.g. auto-refresh completes before user
    clicks Refresh, leaving the reference pointing at a dead wrapper).

    Does NOT call wait() — workers with no event loop would block the GUI.
    Signal-blocking + generation counters are sufficient to discard stale results.
    """
    if worker is not None:
        try:
            worker.blockSignals(True)
        except RuntimeError:
            pass


def cleanup_workers(*workers):
    """Cancel multiple workers at once. Returns None for easy assignment."""
    for w in workers:
        cancel_worker(w)
    return None
