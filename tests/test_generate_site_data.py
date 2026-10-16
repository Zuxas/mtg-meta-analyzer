"""generate_site_data meta.json: recent window, normalized dates (site Strategies page)."""
import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "gsd", Path(__file__).resolve().parents[1] / "scripts" / "generate_site_data.py")
gsd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gsd)


def test_meta_uses_recent_window_and_iso_range():
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE events (id INTEGER PRIMARY KEY, date TEXT, format TEXT);
        CREATE TABLE decks (id INTEGER PRIMARY KEY, event_id INT, archetype TEXT);
    """)
    # old event (outside 30d) full of Old Deck; two recent ones in both date shapes
    for eid, date in [(1, "31/10/25"), (2, "2026-10-10"), (3, "14/10/26"), (4, "2026-10-20")]:
        con.execute("INSERT INTO events VALUES (?,?, 'modern')", (eid, date))
    rows = ([(1, "Old Deck")] * 50 + [(2, "New Deck")] * 3 + [(3, "New Deck"), (3, "Other")]
            + [(4, "Future")] * 9)   # dated after `today`: excluded
    con.executemany("INSERT INTO decks (event_id, archetype) VALUES (?,?)", rows)
    gsd.FORMAT = "modern"
    meta = gsd.generate_meta(con, days=30, today=datetime(2026, 10, 16))
    assert meta["event_range"] == {"min": "2026-10-10", "max": "2026-10-14"}
    assert (meta["total_events"], meta["total_decks"], meta["window_days"]) == (2, 5, 30)
    assert [(a["name"], a["share"]) for a in meta["archetypes"]] == [("New Deck", 80.0), ("Other", 20.0)]
