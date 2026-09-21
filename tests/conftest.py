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
