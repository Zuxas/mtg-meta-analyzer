"""Pytest configuration. Adds project root to sys.path so tests can
import `gui.state`, `gui.widgets.palette_registry`, etc.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _no_leaked_ui_state_saves():
    """Cancel any debounced UIState save left pending by a test.

    UIState saves via threading.Timer. A test that sets state while
    PREFERENCES_PATH is monkeypatched to a tmp file, and does not flush(),
    leaves a timer that fires AFTER the monkeypatch is undone -- into the
    real data/preferences.json. Several such timers racing produced a
    corrupt file on 2026-09-21 (valid JSON + a stale tail) and, most
    likely, the missing `formats` key of 2026-07. This runs after every
    test regardless of which fixtures it used.
    """
    yield
    try:
        from gui.state import UIState
        UIState.cancel_all_pending()
    except Exception:
        pass


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: test may reach the real network (everything else is blocked at DNS)")


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Block real network access in tests unless marked @pytest.mark.network.

    On 2026-09-21 a backfill test with an unstubbed `_get` scraped 20 Vintage
    events from mtgtop8 into the LIVE DB. Tests that mock `requests` are
    unaffected; a genuine socket to a non-local host fails at name resolution,
    the same way it would offline.
    """
    if request.node.get_closest_marker("network"):
        yield
        return
    import socket
    real = socket.getaddrinfo
    local = {None, "", "localhost", "127.0.0.1", "::1"}

    def guarded(host, *args, **kwargs):
        if host in local:
            return real(host, *args, **kwargs)
        raise RuntimeError(f"network access blocked in tests: {host!r} "
                           f"(mark the test @pytest.mark.network if it must)")
    monkeypatch.setattr(socket, "getaddrinfo", guarded)
    yield
