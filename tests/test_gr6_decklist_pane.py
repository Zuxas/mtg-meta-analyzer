"""
Tests for GR-6 (My Decks Decklist pane): grouped-by-type rendering, mana
curve, color pips, card hover, and the "(auto-imported <date>)" suffix
moved out of the displayed deck name (render-only; DB row unchanged).

GR-6 gate (harness/handoffs/mta-gui-polish-2026-07-10.md, amended):
  "pytest-qt asserts the four group headers EACH non-empty for a 75-card
  deck, a curve widget with >=1 nonzero bucket, >=1 pip widget rendered,
  hover wiring fires on a card row, table shows no '(auto-imported'
  substring while the DB row is unchanged (read it back)."

Offscreen-Qt pattern (QT_QPA_PLATFORM=offscreen, no pytest-qt plugin) per
tests/test_gr4_empty_on_open.py. The group/curve/pip/hover assertions only
need a bare DecklistPane.set_deck(dict) -- no MyDecksTab, no background
worker, so most tests here have nothing to drain. Only the last test
(auto-imported name) constructs a real MyDecksTab against a per-test tmp
DB; it drains any worker its QTimer.singleShot(200, ...) auto-load might
spin up before teardown -- Qt 6.10 hard-crashes the whole pytest process
if a QThread is still running when the wrapper is destroyed (see
test_gr4_empty_on_open.py's _quiesce docstring for the full story).
"""
import time

import pytest

from PyQt6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# 75-card fixture deck: 16 creatures / 16 noncreature spells / 28 lands in
# the mainboard (60) + 15 sideboard cards = 75 total, spanning all four
# groups so the gate's "each non-empty" can't pass by accident.
# ---------------------------------------------------------------------------

_MAINBOARD = {
    "Test Creature One":   4,   # Creature, cmc 1
    "Test Creature Two":   4,   # Creature, cmc 2
    "Test Creature Three": 4,   # Creature, cmc 3
    "Test Creature Four":  4,   # Legendary Creature, cmc 4
    "Test Spell One":      4,   # Instant, cmc 1
    "Test Spell Two":      4,   # Sorcery, cmc 2
    "Test Spell Three":    4,   # Artifact, cmc 3
    "Test Spell Four":     4,   # Enchantment, cmc 4
    "Test Land One":       14,  # Land
    "Test Land Two":       14,  # Land -- Forest
}
_SIDEBOARD = {
    "Test SB One":   3,
    "Test SB Two":   3,
    "Test SB Three": 3,
    "Test SB Four":  3,
    "Test SB Five":  3,
}

_CARD_TYPE_DATA = {
    "Test Creature One":   ("Creature — Human Soldier", 1.0),
    "Test Creature Two":   ("Creature — Elf Warrior", 2.0),
    "Test Creature Three": ("Creature — Dragon", 3.0),
    "Test Creature Four":  ("Legendary Creature — Human Wizard", 4.0),
    "Test Spell One":      ("Instant", 1.0),
    "Test Spell Two":      ("Sorcery", 2.0),
    "Test Spell Three":    ("Artifact", 3.0),
    "Test Spell Four":     ("Enchantment", 4.0),
    "Test Land One":       ("Land", 0.0),
    "Test Land Two":       ("Land — Forest", 0.0),
    "Test SB One":         ("Instant", 1.0),
    "Test SB Two":         ("Creature — Cat", 2.0),
    "Test SB Three":       ("Artifact", 3.0),
    "Test SB Four":        ("Enchantment", 2.0),
    "Test SB Five":        ("Land", 0.0),
}

assert sum(_MAINBOARD.values()) == 60
assert sum(_SIDEBOARD.values()) == 15


def _fixture_deck() -> dict:
    return {
        "id": 1,
        "name": "Test Deck",
        "format": "standard",
        "archetype": "Izzet Prowess",
        "mainboard": dict(_MAINBOARD),
        "sideboard": dict(_SIDEBOARD),
        "notes": "",
    }


@pytest.fixture
def seeded_card_data(tmp_path, monkeypatch):
    """Point db.database at a per-test sqlite file seeded with type_line/
    cmc rows for every card in the fixture deck. Mirrors how the real
    card_data table is already populated locally by scrapers.scryfall --
    the pane only ever does a read-only SELECT against it, never a
    scrape/live-API call and never a write."""
    import db.database as dbmod
    db_path = tmp_path / "test_gr6.db"
    monkeypatch.setattr(dbmod, "DB_PATH", str(db_path))
    monkeypatch.setattr(dbmod, "ARCHIVE_PATH", str(tmp_path / "archive_gr6.db"))
    dbmod.init_db()

    conn = dbmod.get_connection()
    try:
        for name, (type_line, cmc) in _CARD_TYPE_DATA.items():
            conn.execute(
                "INSERT INTO card_data (name, type_line, cmc) VALUES (?, ?, ?)",
                (name, type_line, cmc),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


# ---------------------------------------------------------------------------
# (a) grouped-by-type rendering with per-group counts
# ---------------------------------------------------------------------------

def test_four_group_headers_each_nonempty(app, seeded_card_data):
    from gui.widgets.decklist_pane import DecklistPane
    pane = DecklistPane()
    pane.set_deck(_fixture_deck())

    assert set(pane._group_headers) == {"Creatures", "Spells", "Lands", "Sideboard"}
    for group in ("Creatures", "Spells", "Lands", "Sideboard"):
        text = pane._group_headers[group].text()
        assert "(0)" not in text, f"{group} header rendered empty: {text!r}"
        assert "none" not in text.lower()


def test_group_counts_match_fixture(app, seeded_card_data):
    from gui.widgets.decklist_pane import DecklistPane
    pane = DecklistPane()
    pane.set_deck(_fixture_deck())

    assert pane._group_headers["Creatures"].text() == "CREATURES (16)"
    assert pane._group_headers["Spells"].text() == "SPELLS (16)"
    assert pane._group_headers["Lands"].text() == "LANDS (28)"
    assert pane._group_headers["Sideboard"].text() == "SIDEBOARD (15)"


def test_unknown_card_type_falls_back_to_spells_group(app, seeded_card_data):
    """A card absent from card_data (no local row) must still show up
    somewhere in the pane rather than vanishing -- falls back to Spells."""
    from gui.widgets.decklist_pane import classify_card_type
    assert classify_card_type("") == "Spells"
    assert classify_card_type(None) == "Spells"
    assert classify_card_type("Land") == "Lands"
    assert classify_card_type("Basic Land — Island") == "Lands"
    assert classify_card_type("Artifact Creature") == "Creatures"
    assert classify_card_type("Instant") == "Spells"


# ---------------------------------------------------------------------------
# (b) mana curve mini-bar
# ---------------------------------------------------------------------------

def test_mana_curve_has_nonzero_buckets(app, seeded_card_data):
    from gui.widgets.decklist_pane import DecklistPane
    pane = DecklistPane()
    pane.set_deck(_fixture_deck())

    counts = pane._curve._counts
    assert len(counts) == 8
    assert sum(1 for c in counts if c > 0) >= 1
    # Lands must not leak into the curve -- only the 16 creatures + 16
    # noncreature spells (28 lands excluded) contribute.
    assert sum(counts) == 32
    assert counts[1] == 8   # Test Creature One (4) + Test Spell One (4)
    assert counts[2] == 8
    assert counts[3] == 8
    assert counts[4] == 8


def test_mana_curve_widget_set_counts_updates_state(app):
    from gui.widgets.decklist_pane import ManaCurveWidget
    w = ManaCurveWidget()
    assert all(c == 0 for c in w._counts)
    w.set_counts([0, 2, 3, 0, 0, 0, 0, 1])
    assert w._counts == [0, 2, 3, 0, 0, 0, 0, 1]


# ---------------------------------------------------------------------------
# (c) color pips
# ---------------------------------------------------------------------------

def test_pip_widget_rendered_for_deck_archetype(app, seeded_card_data):
    from gui.widgets.decklist_pane import DecklistPane
    pane = DecklistPane()
    pane.set_deck(_fixture_deck())

    assert pane._pip_widget is not None
    assert pane._pip_layout.count() >= 1


def test_no_pip_widget_when_archetype_has_no_known_identity(app, seeded_card_data):
    from gui.widgets.decklist_pane import DecklistPane
    pane = DecklistPane()
    deck = _fixture_deck()
    deck["archetype"] = "Some Totally Unrecognized Pile Name Zzz"
    pane.set_deck(deck)
    assert pane._pip_widget is None


# ---------------------------------------------------------------------------
# (d) card-name hover wiring (install_card_hover)
# ---------------------------------------------------------------------------

def test_hover_fires_on_a_card_row(app, seeded_card_data, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "gui.widgets.card_tooltip.CardTooltip.show_for_card",
        lambda self, name, pos: calls.append(name),
    )

    from gui.widgets.decklist_pane import DecklistPane
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QEnterEvent

    pane = DecklistPane()
    pane.set_deck(_fixture_deck())

    assert pane._name_labels, "no card-name labels were rendered"
    lbl = pane._name_labels[0]
    assert lbl._hover_card_name in _MAINBOARD or lbl._hover_card_name in _SIDEBOARD

    ev = QEnterEvent(QPointF(0, 0), QPointF(0, 0), QPointF(0, 0))
    app.sendEvent(lbl, ev)
    assert calls == [lbl._hover_card_name]


def test_all_card_rows_wired_for_hover(app, seeded_card_data):
    """Every rendered card row (main + side) carries a hover-ready name
    label, not just the first one."""
    from gui.widgets.decklist_pane import DecklistPane
    pane = DecklistPane()
    pane.set_deck(_fixture_deck())

    all_names = set(_MAINBOARD) | set(_SIDEBOARD)
    hovered_names = {lbl._hover_card_name for lbl in pane._name_labels}
    assert hovered_names == all_names


# ---------------------------------------------------------------------------
# (e) auto-imported suffix moved out of the displayed name; DB unchanged
# ---------------------------------------------------------------------------

def test_split_auto_imported_helper():
    from gui.tabs.my_decks import _split_auto_imported
    name, date = _split_auto_imported("Boros Aggro (auto-imported 2026-07-01)")
    assert name == "Boros Aggro"
    assert date == "2026-07-01"

    name2, date2 = _split_auto_imported("Plain Deck Name")
    assert name2 == "Plain Deck Name"
    assert date2 is None


def _pump_until(app, predicate, timeout_s=10.0, interval_s=0.02) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _drain_and_cleanup(app, tab) -> None:
    """Pump the event loop until every DataLoadWorker MyDecksTab is
    holding a reference to has actually finished, THEN call
    tab.cleanup(). See test_gr4_empty_on_open.py's _quiesce docstring:
    calling cleanup() while a worker is still mid-flight forces
    worker_utils.stop_worker() down its QThread.terminate() fallback,
    which can corrupt Qt/interpreter state badly enough to crash a
    LATER, unrelated test -- always drain naturally first."""
    def _idle():
        for w in list(getattr(tab, "_workers", []) or []):
            try:
                if w.isRunning():
                    return False
            except RuntimeError:
                pass
        return True
    _pump_until(app, _idle)
    tab.cleanup()


def test_deck_table_shows_no_auto_imported_substring_db_unchanged(app, seeded_card_data):
    import db.saved_decks as saved_decks
    saved_decks._ensure_tables()
    raw_name = "Boros Aggro (auto-imported 2026-07-01)"
    deck_id = saved_decks.save_deck(
        name=raw_name, format_name="standard", archetype="Boros Aggro",
        mainboard={"Test Land One": 17, "Test Land Two": 17, "Test Creature One": 26},
        sideboard={}, notes="",
    )

    from gui.tabs.my_decks import MyDecksTab
    tab = MyDecksTab()
    try:
        from db.saved_decks import get_decks
        tab._on_decks_loaded(get_decks())

        assert tab._table.rowCount() == 1
        item = tab._table.item(0, 0)
        assert "(auto-imported" not in item.text()
        assert item.text() == "Boros Aggro"
        assert "auto-imported" in (item.toolTip() or "").lower()

        # DB row itself must remain byte-identical -- render-only strip.
        row = saved_decks.get_deck(deck_id)
        assert row["name"] == raw_name
    finally:
        _drain_and_cleanup(app, tab)


def test_show_deck_header_strips_suffix_and_meta_line_carries_badge(app, seeded_card_data):
    """The right-hand detail header must also drop the suffix (it's the
    other place a raw deck name is displayed); the date moves to the
    de-emphasized meta line instead of vanishing."""
    from gui.tabs.my_decks import MyDecksTab
    tab = MyDecksTab()
    try:
        deck = {
            "id": 1,
            "name": "Boros Aggro (auto-imported 2026-07-01)",
            "format": "standard",
            "archetype": "Boros Aggro",
            "mainboard": {"Test Land One": 17, "Test Land Two": 17, "Test Creature One": 26},
            "sideboard": {},
            "notes": "",
        }
        tab._show_deck(deck)
        assert tab._header.text() == "Boros Aggro"
        assert "(auto-imported" not in tab._header.text()
        assert "2026-07-01" in tab._meta_lbl.text()
    finally:
        _drain_and_cleanup(app, tab)
