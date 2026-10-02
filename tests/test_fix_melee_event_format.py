"""Round-based format correction of one Melee event: only `format` changes, counts are pinned."""
import sqlite3

import pytest

from scripts import fix_melee_event_format as fx

SCHEMA = """CREATE TABLE matches (id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, round INTEGER,
    player1 TEXT, player2 TEXT, player1_arch TEXT NOT NULL, player2_arch TEXT NOT NULL, winner_arch TEXT,
    result TEXT, format TEXT NOT NULL, event_date TEXT, source TEXT NOT NULL DEFAULT 'mtgmelee')"""


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "mtg_meta.db"
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=wal")
    con.execute(SCHEMA)
    rows = [(1, 1, "standard"), (2, 1, "pauper"), (3, 4, "standard"), (4, 5, "standard"), (5, 6, "pauper")]
    for rid, rnd, fmt in rows:
        con.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rid, "mtgmelee_9", rnd, f"a{rid}", f"b{rid}", "X", "Y", "X", "player1", fmt,
                     "2026-01-17", "mtgmelee"))
    con.execute("INSERT INTO matches VALUES (99,'mtgmelee_8',4,'c','d','X','Y','X','player1','standard',"
                "'2026-01-17','mtgmelee')")
    con.commit()
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "9.html").write_text("Format: Standard, Pauper")
    monkeypatch.setattr(fx, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(fx, "Path", _redirect(fx.Path, str(meta)))
    return path


def _redirect(real_path, meta_dir):
    class P(type(real_path())):
        def __new__(cls, *a):
            if a and str(a[0]) == r"E:\mtg-data\raw\melee_relabel\event_meta":
                a = (meta_dir,) + a[1:]
            return real_path(*a)
    return P


ARGS = ["--event", "mtgmelee_9", "--rounds", "1-3:standard,4-6:pauper"]


def test_dry_run_refuses_unexpected_counts(db):
    with pytest.raises(SystemExit, match="refusing"):
        fx.main(ARGS + ["--expect", "standard>pauper:1,pauper>standard:1", "--db", str(db)])


def test_commit_changes_only_format_of_that_event(db, tmp_path):
    before = list(sqlite3.connect(db).execute("SELECT * FROM matches ORDER BY id"))
    assert fx.main(ARGS + ["--expect", "standard>pauper:2,pauper>standard:1", "--commit", "--db", str(db)]) == 0
    after = list(sqlite3.connect(db).execute("SELECT * FROM matches ORDER BY id"))
    changed = {b[0]: (b[9], a[9]) for b, a in zip(before, after) if b != a}
    assert changed == {2: ("pauper", "standard"), 3: ("standard", "pauper"), 4: ("standard", "pauper")}
    for b, a in zip(before, after):
        assert b[:9] + b[10:] == a[:9] + a[10:]                # nothing but format
    assert list(tmp_path.glob("mtg_meta.backup-*-pre-melee-format-fix.db"))
    assert fx.plan(sqlite3.connect(db), "mtgmelee_9", fx._round_map("1-3:standard,4-6:pauper")) == []
