"""Basic/Pro progressive disclosure — the tests 9e6bcda never got.

That commit (2026-07-01) shipped the Basic|Pro header toggle, the Pro-only
tab set, a META reorder and the dismissible Dashboard banner to main with
"visual check pending" in its message, no documentation, and no tests at
all. This file closes the test half; the visual checklist lives in
NEXT_STEPS.

What is pinned here, and why each one matters:

  * _PRO_TAB_LABELS membership -- the set decides what a newcomer sees.
  * _is_existing_user(), which picks the FIRST default. Getting it wrong
    either drops an existing user into a stripped-down UI or hands a fresh
    install the full one. It must also survive a database with none of the
    tables it looks for, since that is exactly a fresh install.
  * Round-tripping Basic -> Pro restores the Pro sub-tabs IN ORDER. The
    implementation removes and re-adds tabs, so a naive re-add would append
    them at the end and silently reorder META.
  * _path_has_pro_part, which stops a persisted "last tab" pointing at a
    hidden Pro tab from being restored into Basic mode.
  * Banner dismissal persists.

The MainWindow-level fixtures below are trimmed copies of the canonical
ones in tests/test_event_optimizer_scroll.py (kept local rather than moved
to conftest so that passing file is not disturbed); see its docstrings for
the full reasoning on why each integration must be neutralized.
"""
import sqlite3

import pytest

from PyQt6.QtWidgets import QApplication, QTabWidget


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tmp_prefs(tmp_path, monkeypatch):
    """Per-test preferences.json — these must never read or write the
    developer's real sticky-state file."""
    prefs_path = tmp_path / "preferences.json"
    monkeypatch.setattr("gui.state.PREFERENCES_PATH", prefs_path)
    monkeypatch.setattr("gui.state.UIState._instance", None)
    return prefs_path


@pytest.fixture
def _patched_mainwindow_integrations(monkeypatch):
    """Neutralize MainWindow's startup side effects (live MTGA log parsing
    into a DB write path, a modal setup wizard, OS-level global hotkeys).
    See tests/test_event_optimizer_scroll.py for the full rationale."""
    import gui.mtga_log_watcher as watcher_mod
    import gui.main_window as mw_mod
    import gui.global_hotkey as hotkey_mod

    monkeypatch.setattr(watcher_mod.MtgaLogWatcher, "start", lambda self: None)
    monkeypatch.setattr(mw_mod.MainWindow, "_startup_check", lambda self: None)
    monkeypatch.setattr(
        mw_mod.MainWindow, "_auto_sync_mtga_on_launch", lambda self: None
    )
    monkeypatch.setattr(hotkey_mod, "register_global_hotkeys", lambda hotkeys: None)


@pytest.fixture
def _restore_app_theme(app):
    """MainWindow.__init__ mutates the shared QApplication palette/stylesheet;
    restore them so this file cannot leak global state into siblings."""
    orig_palette = app.palette()
    orig_stylesheet = app.styleSheet()
    yield
    app.setPalette(orig_palette)
    app.setStyleSheet(orig_stylesheet)


# ---------------------------------------------------------------------------
# Pure helpers — no MainWindow needed
# ---------------------------------------------------------------------------

def test_pro_only_tab_labels_are_pinned():
    """The Pro-only set defines the whole feature. Changing it silently
    changes what a new user sees, so it is pinned explicitly."""
    from gui.main_window import _PRO_TAB_LABELS

    assert _PRO_TAB_LABELS == {
        "LADDER", "SIMULATE", "PREDICTIONS", "CALIBRATION", "HYPOTHESES",
    }


def test_path_has_pro_part_detects_hidden_tabs():
    """A persisted tab path pointing into a Pro tab must be recognised, so
    Basic mode does not try to restore a tab it has hidden."""
    from gui.main_window import MainWindow

    assert MainWindow._path_has_pro_part("META/LADDER") is True
    assert MainWindow._path_has_pro_part("TOURNAMENT/HYPOTHESES") is True
    assert MainWindow._path_has_pro_part("META/CHARTS") is False
    assert MainWindow._path_has_pro_part("DASHBOARD") is False


# ---------------------------------------------------------------------------
# _is_existing_user — picks the first-run default
# ---------------------------------------------------------------------------

def _point_db_at(monkeypatch, path):
    """Redirect db.database.DB_PATH, which _is_existing_user imports
    locally at call time."""
    import db.database as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(path))


def test_is_existing_user_false_when_no_database_file(tmp_path, monkeypatch):
    """A fresh install has no DB at all -> Basic, and crucially the check
    must not create an empty database file as a side effect."""
    from gui.main_window import _is_existing_user

    missing = tmp_path / "nope.db"
    _point_db_at(monkeypatch, missing)
    assert _is_existing_user() is False
    assert not missing.exists(), "_is_existing_user must not create the DB"


def test_is_existing_user_false_when_tables_absent(tmp_path, monkeypatch):
    """A real but bare database (neither saved_decks nor match_log) is a
    fresh install, not a crash -- each table read is individually guarded."""
    from gui.main_window import _is_existing_user

    db = tmp_path / "bare.db"
    sqlite3.connect(str(db)).close()
    _point_db_at(monkeypatch, db)
    assert _is_existing_user() is False


def test_is_existing_user_false_when_tables_are_empty(tmp_path, monkeypatch):
    """Tables present but empty is still a fresh install."""
    from gui.main_window import _is_existing_user

    db = tmp_path / "empty.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE saved_decks (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE match_log (id INTEGER PRIMARY KEY)")
    con.commit(); con.close()
    _point_db_at(monkeypatch, db)
    assert _is_existing_user() is False


@pytest.mark.parametrize("table", ["saved_decks", "match_log"])
def test_is_existing_user_true_from_either_table(tmp_path, monkeypatch, table):
    """A row in EITHER table means a real user, who must keep the full UI."""
    from gui.main_window import _is_existing_user

    db = tmp_path / f"{table}.db"
    con = sqlite3.connect(str(db))
    con.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
    con.execute(f"INSERT INTO {table} (id) VALUES (1)")
    con.commit(); con.close()
    _point_db_at(monkeypatch, db)
    assert _is_existing_user() is True


# ---------------------------------------------------------------------------
# MainWindow-level behaviour
# ---------------------------------------------------------------------------

def _build(monkeypatch=None):
    from gui.main_window import MainWindow
    return MainWindow()


def _meta_labels(win):
    """META sub-tab labels in their current visual order."""
    tw = win._meta_tab
    return [tw.tabText(i) for i in range(tw.count())]


def _all_labels(win):
    """Every sub-tab label anywhere in the window, for presence checks."""
    labels = []
    for tw in win.findChildren(QTabWidget):
        labels.extend(tw.tabText(i) for i in range(tw.count()))
    return labels


def test_persisted_ui_level_is_respected_over_the_heuristic(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme,
    monkeypatch,
):
    """Once the user has chosen, _is_existing_user must not be consulted
    again -- otherwise gaining a saved deck would silently flip them to Pro."""
    import gui.main_window as mw_mod
    from gui.state import UIState
    from gui.state_keys import UI_LEVEL

    UIState.instance().set(UI_LEVEL, "basic")
    monkeypatch.setattr(
        mw_mod, "_is_existing_user",
        lambda: (_ for _ in ()).throw(AssertionError("heuristic re-consulted")),
    )
    win = None
    try:
        win = _build()
        assert win._ui_level == "basic"
    finally:
        if win is not None:
            win.cleanup()


def test_basic_mode_hides_every_pro_tab(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme,
):
    from gui.main_window import _PRO_TAB_LABELS
    from gui.state import UIState
    from gui.state_keys import UI_LEVEL

    UIState.instance().set(UI_LEVEL, "basic")
    win = None
    try:
        win = _build()
        visible = set(_all_labels(win))
        leaked = visible & _PRO_TAB_LABELS
        assert not leaked, f"Basic mode still shows Pro tabs: {sorted(leaked)}"
    finally:
        if win is not None:
            win.cleanup()


def test_pro_mode_shows_every_pro_tab(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme,
):
    from gui.main_window import _PRO_TAB_LABELS
    from gui.state import UIState
    from gui.state_keys import UI_LEVEL

    UIState.instance().set(UI_LEVEL, "pro")
    win = None
    try:
        win = _build()
        visible = set(_all_labels(win))
        missing = _PRO_TAB_LABELS - visible
        assert not missing, f"Pro mode is missing tabs: {sorted(missing)}"
    finally:
        if win is not None:
            win.cleanup()


def test_round_trip_restores_meta_order_exactly(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme,
):
    """The regression this feature is most likely to cause.

    Switching to Basic REMOVES tabs and switching back re-adds them. If the
    re-add appends instead of restoring position, META silently reorders and
    the user's tabs move around under them. Pin the exact order across a
    full Pro -> Basic -> Pro cycle.
    """
    from gui.state import UIState
    from gui.state_keys import UI_LEVEL

    UIState.instance().set(UI_LEVEL, "pro")
    win = None
    try:
        win = _build()
        before = _meta_labels(win)
        # The documented Pro order (LADDER ahead of PREDICTIONS -- the
        # reorder half of 9e6bcda).
        assert before == [
            "CHARTS", "MATCHUP DATA", "LADDER",
            "SIMULATE", "PREDICTIONS", "CALIBRATION",
        ], before

        win._set_ui_level("basic")
        assert _meta_labels(win) == ["CHARTS", "MATCHUP DATA"]

        win._set_ui_level("pro")
        assert _meta_labels(win) == before, (
            "META order changed across a Basic/Pro round trip: "
            f"{_meta_labels(win)} != {before}"
        )
    finally:
        if win is not None:
            win.cleanup()


def test_ui_level_toggle_persists(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme,
):
    """The choice must survive a restart, which is the whole point of
    putting it in ui_state."""
    from gui.state import UIState
    from gui.state_keys import UI_LEVEL

    UIState.instance().set(UI_LEVEL, "pro")
    win = None
    try:
        win = _build()
        win._set_ui_level("basic")
        assert UIState.instance().get(UI_LEVEL) == "basic"
    finally:
        if win is not None:
            win.cleanup()


def test_banner_hidden_once_dismissed(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme,
):
    """A dismissed banner must stay dismissed on the next launch."""
    from gui.state import UIState
    from gui.state_keys import DASH_BANNER_DISMISSED, UI_LEVEL

    UIState.instance().set(UI_LEVEL, "pro")
    UIState.instance().set(DASH_BANNER_DISMISSED, True)
    win = None
    try:
        win = _build()
        assert win._dash_banner is None
    finally:
        if win is not None:
            win.cleanup()


def test_banner_present_when_not_dismissed(
    app, tmp_prefs, _patched_mainwindow_integrations, _restore_app_theme,
):
    """Counterpart to the test above -- proves that one is not passing
    simply because the banner never appears at all."""
    from gui.state import UIState
    from gui.state_keys import UI_LEVEL

    UIState.instance().set(UI_LEVEL, "pro")
    win = None
    try:
        win = _build()
        assert win._dash_banner is not None
    finally:
        if win is not None:
            win.cleanup()
