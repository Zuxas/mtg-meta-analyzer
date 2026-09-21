"""Pytest configuration. Adds project root to sys.path so tests can
import `gui.state`, `gui.widgets.palette_registry`, etc.
"""
import os
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
    config.addinivalue_line(
        "markers", "live_db: test reads the real mtg_meta.db (everything else gets an empty tmp DB)")


def _norm(path) -> str:
    import os
    return os.path.normcase(os.path.abspath(str(path)))


# The configured live DB paths, captured once at import so the guard below can
# recognise every copy of them that other modules captured at THEIR import.
import db.database as _dbm                      # noqa: E402
LIVE_DB_PATHS = frozenset({_norm(_dbm.DB_PATH), _norm(_dbm.ARCHIVE_PATH)})


@pytest.fixture(autouse=True)
def _no_live_db(request, monkeypatch, tmp_path_factory):
    """Point every DB path at an EMPTY tmp file unless @pytest.mark.live_db.

    Two incidents on 2026-09-21: a backfill test with an unstubbed fetch wrote
    20 real Vintage events into the live mtg_meta.db, and
    test_generation_is_deterministic flaked while the backfill inserted decks
    between its two calls. Default-deny, like the network guard.

    `db.database.DB_PATH` is not enough: ~25 modules do
    `from db.database import DB_PATH as CENTRAL_DB_PATH` at import, so every
    already-imported module holding one of the live paths is redirected too.
    Modules imported later (inside the test) capture the patched value.
    A test that needs tables calls `init_db()` itself, as the existing tmp-DB
    fixtures already do; one that silently relied on live data now fails with
    `no such table` instead of passing on data it never declared.
    """
    if request.node.get_closest_marker("live_db"):
        yield
        return
    import sys
    tmp = tmp_path_factory.mktemp("db")
    live = {_norm(_dbm.DB_PATH): _dbm.DB_PATH, _norm(_dbm.ARCHIVE_PATH): _dbm.ARCHIVE_PATH}
    new = {_norm(_dbm.DB_PATH): str(tmp / "mtg_meta.db"),
           _norm(_dbm.ARCHIVE_PATH): str(tmp / "mtg_archive.db")}
    monkeypatch.setattr(_dbm, "DB_PATH", new[_norm(_dbm.DB_PATH)])
    monkeypatch.setattr(_dbm, "ARCHIVE_PATH", new[_norm(_dbm.ARCHIVE_PATH)])
    _redirect_captured_paths(new, monkeypatch)
    yield
    # A module first imported INSIDE the test captured the tmp path and no
    # monkeypatch entry exists for it -- put those back to the live paths so a
    # later @live_db test (or a module-level cache) does not inherit the tmp DB.
    back = {_norm(v): live[k] for k, v in new.items()}
    _redirect_captured_paths(back)


def _redirect_captured_paths(mapping, monkeypatch=None):
    """setattr every module-level *_DB_PATH whose value is a key of `mapping`."""
    import sys
    for mod in list(sys.modules.values()):
        if mod is None or mod is _dbm:
            continue
        for attr in ("CENTRAL_DB_PATH", "DB_PATH", "ARCHIVE_PATH", "ARCHIVE_DB_PATH"):
            try:
                val = getattr(mod, attr, None)
            except Exception:
                continue
            if isinstance(val, (str, os.PathLike)) and _norm(val) in mapping:
                target = mapping[_norm(val)]
                if monkeypatch is not None:
                    monkeypatch.setattr(mod, attr, target)
                else:
                    setattr(mod, attr, target)


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
