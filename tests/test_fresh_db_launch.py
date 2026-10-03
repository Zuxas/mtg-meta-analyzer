"""The app must start on a database that only db.database.init_db built.

WHY THIS EXISTS
---------------
init_db() creates just 7 real tables (bookmarks, card_data, cards,
deck_cards, decks, events, guides) while the app reads ~19. The rest are
created elsewhere -- most on demand via ensure_table helpers, but the
untapped_* tables and views ONLY by scrapers/untapped_mythic_scraper.py.

That asymmetry produced a launch-blocking bug: LadderMetaTab.__init__ calls
refresh() eagerly, which queried untapped_entries through a raw
sqlite3.connect with no guard, so on any database where the Untapped
pipeline had never run the error propagated out of MainWindow._build_ui and
the application simply never opened. A fresh clone could not start the
program at all.

A one-off audit (2026-09-22) probed every tab against a purpose-built fresh
database and found untapped_entries was the only such case. This test makes
that audit permanent: add a tab, or an eager unguarded query on a
scraper-created table, and it fails here instead of on a user's machine.

DESIGN
------
Everything runs in a SUBPROCESS, deliberately:

  * Several modules bind their database path at import time (e.g.
    db.untapped_queries.DB_PATH = Path(CENTRAL_DB_PATH)), so monkeypatching
    the environment after pytest has already imported them would not take
    effect. A fresh interpreter with MTG_META_DB set is the only faithful
    simulation of a fresh install.
  * Constructing ~17 Qt tabs leaves timers and background workers behind.
    Isolating that in a child process keeps it out of the pytest process,
    where a stray QThread at teardown is fatal under Qt 6.10.

The child holds a reference to every widget it builds and exits via
os._exit. Dropping a tab on the floor lets Python collect it while its
DataLoadWorker thread is still running, and Qt 6.10 turns that into SIGABRT
(exit 134) -- which killed this probe before it could print any verdict, and
looked exactly like "the tab is broken". Holding the reference until the
process dies avoids the destructor entirely.

The whole probe takes well under a second per tab.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent

# Mirrors the construction list in gui/main_window.py::_build_ui.
TABS = [
    ("DashboardTab", "gui.tabs.dashboard"),
    ("DeckAnalyzerTab", "gui.tabs.deck_analyzer"),
    ("SearchTab", "gui.tabs.search"),
    ("ChartsTab", "gui.tabs.charts"),
    ("PredictionsTab", "gui.tabs.predictions"),
    ("KnowledgeBaseTab", "gui.tabs.knowledge_base"),
    ("TournamentPrepTab", "gui.tabs.tournament_prep"),
    ("HeatmapTab", "gui.tabs.heatmap_tab"),
    ("LadderMetaTab", "gui.tabs.ladder_meta"),
    ("SimulateTab", "gui.tabs.simulate"),
    ("CalibrationTab", "gui.tabs.calibration"),
    ("MyDecksTab", "gui.tabs.my_decks"),
    ("MatchLogTab", "gui.tabs.match_log"),
    ("AskClaudeTab", "gui.tabs.ask_claude"),
    ("SetAnalysisTab", "gui.tabs.set_analysis"),
    ("PuzzlesTab", "gui.tabs.puzzles"),
    ("SettingsTab", "gui.tabs.settings"),
]

_CHILD = textwrap.dedent("""
    import os, sys, traceback, importlib
    from db.database import init_db
    init_db()                       # the fresh-install database

    from PyQt6.QtWidgets import QApplication
    app = QApplication([])

    TABS = {tabs!r}
    failures = []
    keep = []          # MUST hold references -- see note below
    for cls_name, mod_name in TABS:
        try:
            keep.append(getattr(importlib.import_module(mod_name), cls_name)())
        except Exception as exc:
            where = ""
            for fr in traceback.extract_tb(sys.exc_info()[2]):
                if "/gui/" in fr.filename or "/db/" in fr.filename:
                    where = fr.filename.split("mtg-meta-analyzer/")[-1] + ":" + str(fr.lineno)
            failures.append(cls_name + " -> " + type(exc).__name__ + ": " + str(exc) + " @ " + where)

    if {with_main_window!r}:
        try:
            import gui.main_window as mw
            for attr in ("_startup_check", "_auto_sync_mtga_on_launch"):
                if hasattr(mw.MainWindow, attr):
                    setattr(mw.MainWindow, attr, lambda self: None)
            keep.append(mw.MainWindow())
        except Exception as exc:
            failures.append("MainWindow -> " + type(exc).__name__ + ": " + str(exc))

    print("PROBE_FAILURES:" + "||".join(failures))
    sys.stdout.flush()   # os._exit skips buffer flushing
    os._exit(0)          # skip Qt teardown; the verdict is already printed
""")


def _run_probe(tmp_path, tabs, with_main_window):
    env = dict(os.environ)
    env["MTG_META_DB"] = str(tmp_path / "fresh.db")
    env["MTG_META_ARCHIVE_DB"] = str(tmp_path / "fresh_archive.db")
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD.format(tabs=tabs, with_main_window=with_main_window)],
        capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT), env=env,
    )
    marker = "PROBE_FAILURES:"
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            payload = line[len(marker):].strip()
            return [f for f in payload.split("||") if f]
    raise AssertionError(
        "probe produced no verdict (crashed before reporting)\n"
        f"exit={proc.returncode}\nstdout:\n{proc.stdout[-2000:]}\n"
        f"stderr:\n{proc.stderr[-2000:]}"
    )


@pytest.fixture(scope="module")
def _qt_available():
    pytest.importorskip("PyQt6")


@pytest.mark.parametrize("cls_name,mod_name", TABS, ids=[t[0] for t in TABS])
def test_tab_constructs_on_a_fresh_database(
    _qt_available, tmp_path, cls_name, mod_name
):
    """No tab may raise when only init_db() has run.

    A failure here is almost certainly an eager query, in that tab's
    __init__, against a table init_db does not create -- the exact shape of
    the untapped_entries launch bug.

    One subprocess PER TAB, not one for all of them: constructing every tab
    in a single interpreter leaves enough live QThread workers that Qt 6.10
    aborts the process (SIGABRT on "QThread: Destroyed while thread is still
    running") before any verdict can be printed, which reads as an
    infrastructure failure rather than naming the guilty tab. Per-tab
    isolation also means one broken tab reports itself by name instead of
    masking the rest.
    """
    failures = _run_probe(tmp_path, [(cls_name, mod_name)], with_main_window=False)
    assert not failures, (
        f"{cls_name} failed to construct on a fresh database:\n  "
        + "\n  ".join(failures)
    )


def test_main_window_constructs_on_a_fresh_database(_qt_available, tmp_path):
    """The end-to-end gate: MainWindow builds every tab, so this is what a
    real first launch does. Pre-fix this raised OperationalError and the app
    never opened."""
    failures = _run_probe(tmp_path, [], with_main_window=True)
    assert not failures, (
        "MainWindow failed to construct on a fresh database -- the app would "
        "not launch:\n  " + "\n  ".join(failures)
    )


def test_probe_harness_actually_detects_a_broken_tab(_qt_available, tmp_path):
    """Guard against a false all-clear.

    An audit that cannot fail proves nothing, so point the probe at a class
    that raises on construction and assert it is reported. Without this, a
    typo in the probe would read as "every tab is fine".
    """
    failures = _run_probe(
        tmp_path,
        [("NoSuchTabClass", "gui.tabs.dashboard")],
        with_main_window=False,
    )
    assert failures, "probe reported success for a class that cannot exist"
    assert "NoSuchTabClass" in failures[0]
