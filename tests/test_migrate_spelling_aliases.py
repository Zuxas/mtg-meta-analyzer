import sqlite3

from scripts import migrate_spelling_aliases as m


def _db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE decks (id INTEGER PRIMARY KEY, archetype TEXT)")
    c.executemany("INSERT INTO decks (archetype) VALUES (?)",
                  [("Merfolks",), ("Merfolks",), ("Merfolk",), ("Rakdos Affinity",), ("Weenie White",), (None,)])
    c.commit()
    c.close()


def test_touches_only_the_approved_spellings(tmp_path):
    db = tmp_path / "t.db"
    _db(db)
    assert m.main(["--commit", "--db", str(db)]) == 0
    c = sqlite3.connect(db)
    labels = sorted((r[0] or "") for r in c.execute("SELECT archetype FROM decks"))
    assert labels == ["", "Merfolk", "Merfolk", "Merfolk", "Rakdos Affinity", "White Weenie"]
    assert list(tmp_path.glob("t.backup-*-pre-aliases.db")), "backup written first"


def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "t.db"
    _db(db)
    m.main(["--db", str(db)])
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM decks WHERE archetype='Merfolks'").fetchone()[0] == 2


def test_every_key_is_in_the_alias_table():
    from analysis.archetypes import ALIASES
    assert all(k in ALIASES for k in m.KEYS_2026_09_28) and len(m.KEYS_2026_09_28) == 46
