"""Matchup spread card on Match Log (tmp DB via the conftest live-DB guard)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def seeded():
    from db import saved_decks
    from db.database import get_connection, init_db
    from db.match_log import _ensure_table
    init_db()
    _ensure_table()
    saved_decks._ensure_tables()
    rows = ([("Boros Energy", "Green Tron", "loss", "play", "MTGO Casual")] * 2
            + [("Boros Energy", "Green Tron", r, "draw", "Modern Challenge 32")
               for r in ("loss", "loss", "win", "loss")]
            + [("Boros Energy", "", "win", "play", "MTGO Casual")]
            + [("5C Humans", "Burn", "win", "play", "x")])
    with get_connection() as con:
        con.executemany(
            "INSERT INTO match_log (event_name, event_date, format, my_deck, opp_deck, result, "
            "play_draw, created_at) VALUES (?, '2026-09-26', 'modern', ?, ?, ?, ?, 'x')",
            [(e, d, o, r, pd) for d, o, r, pd, e in rows])


def _wait(app, card, secs=5.0):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        if all(not w.isRunning() for w in list(card._workers) if _alive(w)):
            app.processEvents()
            return
        time.sleep(0.02)


def _alive(w):
    try:
        w.isRunning()
        return True
    except RuntimeError:
        return False


def _texts(widget):
    return [lbl.text() for lbl in widget.findChildren(QLabel)]


def test_card_shows_kpis_rows_and_unknown_bucket(app, seeded):
    from gui.widgets.matchup_spread_card import MatchupSpreadCard
    card = MatchupSpreadCard()
    card._format = "modern"
    card.load_decks(preferred="Boros Energy")
    _wait(app, card)
    t = _texts(card)
    assert card.deck() == "Boros Energy"
    assert "2-5" in t                                        # record KPI
    assert "Green Tron" in t and "Unknown opponent" in t
    assert any("LOSING" in s or "BELOW META" in s or "CRITICAL" in s for s in t)
    card.cleanup()


def test_competitive_toggle_drops_casual_games(app, seeded):
    from gui.widgets.matchup_spread_card import MatchupSpreadCard
    card = MatchupSpreadCard()
    card._format = "modern"
    card.load_decks(preferred="Boros Energy")
    _wait(app, card)
    card._mode.set_value("Competitive", emit=True)
    _wait(app, card)
    t = _texts(card)
    assert "1-3" in t and "Unknown opponent" not in t
    assert any("small sample" in s for s in t)                # 4 games < MIN_ADVICE_N
    card.cleanup()


def test_deck_picker_lists_text_labelled_decks(app, seeded):
    from gui.widgets.matchup_spread_card import MatchupSpreadCard
    card = MatchupSpreadCard()
    card.load_decks()
    _wait(app, card)
    items = [card._deck.itemData(i) for i in range(card._deck.count())]
    assert items == ["Boros Energy", "5C Humans"]
    card.cleanup()
