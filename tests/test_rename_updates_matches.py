"""#32 (write side): archetype renames update `matches` with `decks`, in the
same transaction, so one archetype stops splitting across old and new labels
in real win rates and matchups."""
import pytest

from analysis import archetypes as A


@pytest.fixture
def con():
    from db.database import get_connection, init_db
    init_db()
    c = get_connection()
    ev = c.execute("INSERT INTO events (source_id, source, name, date, format) "
                   "VALUES ('e1', 'test', 'Event', '2026-10-01', 'modern')").lastrowid
    for i, arch in enumerate(["Merfolks", "Merfolks", "Merfolk", "Zoo"]):
        c.execute("INSERT INTO decks (event_id, source_id, archetype, placement) "
                  "VALUES (?, ?, ?, ?)", (ev, f"d{i}", arch, i + 1))
    rows = [("Merfolks", "Zoo", "Merfolks", "player1"),
            ("Zoo", "Merfolks", "Zoo", "player1"),
            ("Merfolk", "Zoo", "Merfolk", "player1"),
            ("Death & Taxes", "Zoo", "Zoo", "player2"),     # label only in matches
            ("Zoo", "Tron", "Tron", "player2")]
    for i, (a, b, w, r) in enumerate(rows):
        c.execute("INSERT INTO matches (event_id, round, player1, player2, player1_arch, "
                  "player2_arch, winner_arch, result, format) "
                  "VALUES ('m', ?, 'p', 'q', ?, ?, ?, ?, 'modern')", (i, a, b, w, r))
    c.commit()
    yield c
    c.close()


def _labels(c):
    decks = sorted(r[0] for r in c.execute("SELECT archetype FROM decks"))
    m = c.execute("SELECT player1_arch, player2_arch, winner_arch FROM matches ORDER BY round").fetchall()
    return decks, [tuple(r) for r in m]


def test_apply_normalization_renames_both_tables(con):
    out = A.apply_normalization(dry_run=False)
    raws = {c[0] for c in out["changes"]}
    assert {"Merfolks", "Death & Taxes"} <= raws          # matches-only label included
    decks, m = _labels(con)
    assert decks == ["Merfolk", "Merfolk", "Merfolk", "Zoo"]
    assert m == [("Merfolk", "Zoo", "Merfolk"),
                 ("Zoo", "Merfolk", "Zoo"),
                 ("Merfolk", "Zoo", "Merfolk"),
                 ("Death And Taxes", "Zoo", "Zoo"),
                 ("Zoo", "Tron", "Tron")]


def test_dry_run_changes_nothing(con):
    before = _labels(con)
    out = A.apply_normalization(dry_run=True)
    assert out["mapped"] >= 2
    assert _labels(con) == before


def test_merge_archetypes_updates_matches_too(con):
    assert A.merge_archetypes("Merfolk", "Merfolks") == 2
    decks, m = _labels(con)
    assert "Merfolks" not in decks
    assert all("Merfolks" not in row for row in m)
    assert m[0] == ("Merfolk", "Zoo", "Merfolk") and m[1] == ("Zoo", "Merfolk", "Zoo")


def test_rename_reports_rows_and_leaves_quarantine_alone(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(matches_excluded)")]
    assert {"player1_arch", "player2_arch"} <= set(cols)
    con.execute("INSERT INTO matches_excluded (id, event_id, round, player1, player2, "
                "player1_arch, player2_arch, winner_arch, result, format, source, "
                "excluded_reason, excluded_scope, excluded_at) "
                "VALUES (999, 'x', 1, 'p', 'q', 'Merfolks', 'Zoo', 'Merfolks', 'player1', "
                "'modern', 'mtgmelee', 'test', 'event', '2026-10-18')")
    assert A.rename_archetype(con, "Merfolks", "Merfolk") == (2, 2)
    con.commit()
    kept = con.execute("SELECT player1_arch FROM matches_excluded WHERE id=999").fetchone()[0]
    assert kept == "Merfolks"


def test_alias_chains_end_on_the_final_name_in_any_order(con, monkeypatch):
    chain = {"Merfolks": "Merfolk", "Merfolk": "Fish", "Death & Taxes": "Merfolks"}
    monkeypatch.setattr(A, "normalize", lambda n, **kw: chain.get(n, n))
    A.apply_normalization(dry_run=False)
    decks, m = _labels(con)
    assert decks == ["Fish", "Fish", "Fish", "Zoo"]
    assert m[0] == ("Fish", "Zoo", "Fish") and m[3][0] == "Fish"   # matches-only label too
    assert A.apply_normalization(dry_run=True)["mapped"] == 0
