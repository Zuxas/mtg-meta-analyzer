"""Empty charts must say what would actually fix them.

Both chart surfaces already showed *something* on an empty database --
"No data to display." on the Dashboard canvas, "No meta data available for
this selection." on the Charts tab -- so neither was blank. The problem was
what they said:

  * Neither named a next action, while the Dashboard panels directly above
    them now do ("Scrape some events from Settings -> Collect More Data").
    A newcomer got three panels telling them what to do and a chart beneath
    saying nothing actionable.
  * "for this selection" implies the SELECTION is at fault. On a fresh
    install the truth is there is no data for any selection, so that wording
    sends the user to fiddle with dropdowns that cannot help.

`chart_canvas._no_data_hint()` appends a second line, branching on whether
the database holds any events at all, because the two cases have opposite
fixes. It is best-effort: any failure returns "" so a hint can never break a
chart that would otherwise render.

Left alone deliberately: loading and error messages, "No archetypes
selected." (a user-action state, already actionable), and the Untapped and
heatmap messages, which already explained their cause and fix.
"""
import sqlite3

import pytest


def _point_at(monkeypatch, db_path):
    """Redirect db.database.get_connection, which _no_data_hint imports at
    call time."""
    import db.database as dbmod

    def _fake_get_connection():
        return sqlite3.connect(str(db_path))

    monkeypatch.setattr(dbmod, "get_connection", _fake_get_connection)


def test_hint_says_scrape_when_nothing_has_been_scraped(tmp_path, monkeypatch):
    """The fresh-install case: an events table with no rows."""
    from gui.widgets.chart_canvas import _no_data_hint

    db = tmp_path / "empty.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")
    con.commit(); con.close()
    _point_at(monkeypatch, db)

    hint = _no_data_hint()
    assert "Collect More Data" in hint
    assert "wider timeframe" not in hint, (
        "with nothing scraped, widening the timeframe cannot help"
    )


def test_hint_says_widen_when_data_exists(tmp_path, monkeypatch):
    """Data exists but this slice is empty -- the opposite advice."""
    from gui.widgets.chart_canvas import _no_data_hint

    db = tmp_path / "populated.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")
    con.execute("INSERT INTO events (id) VALUES (1)")
    con.commit(); con.close()
    _point_at(monkeypatch, db)

    hint = _no_data_hint()
    assert "wider timeframe" in hint
    assert "Collect More Data" not in hint, (
        "with data present, telling the user to scrape is the wrong fix"
    )


def test_hint_is_empty_rather_than_raising_when_the_db_is_unusable(
    tmp_path, monkeypatch
):
    """A hint must never break a chart. A file that is not a database would
    raise on query; the helper has to swallow that and return ""."""
    from gui.widgets.chart_canvas import _no_data_hint

    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"definitely not sqlite" * 32)
    _point_at(monkeypatch, bad)

    assert _no_data_hint() == ""


def test_hint_is_empty_when_get_connection_itself_explodes(monkeypatch):
    """Same guarantee for a failure before any query runs."""
    import db.database as dbmod
    from gui.widgets.chart_canvas import _no_data_hint

    def _boom():
        raise RuntimeError("no database configured")

    monkeypatch.setattr(dbmod, "get_connection", _boom)
    assert _no_data_hint() == ""


def _show_message_calls() -> list[str]:
    """Every show_message(...) call in chart_canvas, as source text.

    Scans CALL SITES rather than the whole module: _no_data_hint's own
    docstring quotes the old strings as examples of what was wrong, and a
    naive whole-source scan matches that prose instead of the real code.
    """
    import inspect
    import re

    import gui.widgets.chart_canvas as mod

    src = inspect.getsource(mod)
    # Call plus a generous window, since some messages wrap onto a second line.
    return [src[m.start():m.start() + 260]
            for m in re.finditer(r"self\.show_message\(", src)]


def test_selection_wording_is_gone_from_the_call_sites():
    """Pin the specific misleading string.

    "No meta data available for this selection." blamed the user's dropdown
    choice for what is usually an empty database. If it returns to a call
    site, the branch above is being bypassed.
    """
    offenders = [c for c in _show_message_calls() if "for this selection" in c]
    assert not offenders, f"misleading wording back at {len(offenders)} call site(s)"


def test_terse_empty_messages_all_carry_the_hint():
    """Every data-empty message routes through _no_data_hint().

    Without this, a new chart type added later quietly reintroduces a
    dead-end message.
    """
    calls = _show_message_calls()
    for msg in (
        '"No data loaded."',
        '"No data to display."',
        '"No meta data available."',
        '"No trend data available for these archetypes."',
    ):
        matching = [c for c in calls if c.startswith(f"self.show_message({msg}")
                    or f"show_message({msg}" in c[:60]]
        assert matching, f"{msg} no longer a show_message call -- update this test"
        assert any("_no_data_hint()" in c for c in matching), (
            f"{msg} is missing its hint"
        )


def test_overlay_wraps_so_the_second_line_is_readable():
    """The hints are long; without word wrap they would be clipped."""
    pytest.importorskip("PyQt6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from gui.widgets.chart_canvas import ChartCanvas

    app = QApplication.instance() or QApplication([])
    c = ChartCanvas()
    try:
        assert c._overlay.wordWrap() is True
    finally:
        c.deleteLater()
        app.processEvents()
