"""Central registry of `matches` rows that are not valid constructed 1v1 observations.

Analytics read `matches` directly in many places (win_rates, conversion, ratings, data_health,
dashboard, heatmap, ...), so excluded rows are not filtered at read time -- they are MOVED, unchanged
and with their original id, into `matches_excluded`, and the registry `excluded_events` records why.
Every reader then excludes them with no code change, the rows stay auditable, and
`db.matches_queries.save_matches` (the only writer) consults the registry so a re-scrape cannot
put them back.

Registry entries are either a whole event (`round` NULL, scope 'event') or one round of an event
(scope 'round'). Moves and restores go through scripts/quarantine_matches.py (backup + one
transaction). Added 2026-10-02 for Draft/Sealed rounds of mixed-format Melee events (150 rows,
58 event+round entries), proven by each round's pairing-level match Format. Team-format events
were NOT quarantined: their public pairings are valid individual 1v1 seat matches, so those rows
stayed in `matches` and only their `format` was corrected from pairing-level evidence.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MATCH_COLS = ("id", "event_id", "round", "player1", "player2", "player1_arch", "player2_arch",
              "winner_arch", "result", "format", "event_date", "source")

CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS excluded_events (
        source      TEXT    NOT NULL,
        event_id    TEXT    NOT NULL,
        round       INTEGER,                       -- NULL = the whole event
        scope       TEXT    NOT NULL CHECK (scope IN ('event', 'round')),
        reason      TEXT    NOT NULL,
        evidence    TEXT,
        created_at  TEXT    NOT NULL,
        CHECK ((scope = 'event') = (round IS NULL))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_excluded_events
        ON excluded_events(source, event_id, IFNULL(round, -2147483648));
    CREATE TABLE IF NOT EXISTS matches_excluded (
        id            INTEGER PRIMARY KEY,         -- the row's ORIGINAL matches.id
        event_id      TEXT    NOT NULL,
        round         INTEGER,
        player1       TEXT,
        player2       TEXT,
        player1_arch  TEXT    NOT NULL,
        player2_arch  TEXT    NOT NULL,
        winner_arch   TEXT,
        result        TEXT,
        format        TEXT    NOT NULL,
        event_date    TEXT,
        source        TEXT    NOT NULL,
        excluded_reason TEXT  NOT NULL,
        excluded_scope  TEXT  NOT NULL,
        excluded_at     TEXT  NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_matches_excluded_event ON matches_excluded(event_id);
"""


def ensure_tables(conn) -> None:
    conn.executescript(CREATE_SQL)


def load_registry(conn) -> tuple[set, set]:
    """(whole events {(source, event_id)}, rounds {(source, event_id, round)}). Empty if the
    registry table does not exist yet (a fresh or test DB)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='excluded_events'").fetchone():
        return set(), set()
    events, rounds = set(), set()
    for source, event_id, rnd in conn.execute("SELECT source, event_id, round FROM excluded_events"):
        if rnd is None:
            events.add((source, event_id))
        else:
            rounds.add((source, event_id, rnd))
    return events, rounds


def is_excluded(source: str, event_id: str, rnd, registry: tuple[set, set]) -> bool:
    events, rounds = registry
    return (source, event_id) in events or (source, event_id, rnd) in rounds


def split_rows(rows: list[dict], registry: tuple[set, set]) -> tuple[list[dict], list[dict]]:
    """(kept, skipped) for match dicts about to be saved."""
    kept, skipped = [], []
    for m in rows:
        excluded = is_excluded(m.get("source", "mtgmelee"), m["event_id"], m.get("round"), registry)
        (skipped if excluded else kept).append(m)
    return kept, skipped


def excluded_summary(conn) -> dict:
    """Audit counts: registry entries and quarantined rows by reason / scope / format."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='matches_excluded'").fetchone():
        return {"registry_entries": 0, "rows": 0, "by_reason": {}, "by_format": {}}
    entries = conn.execute("SELECT COUNT(*) FROM excluded_events").fetchone()[0]
    rows = conn.execute("SELECT COUNT(*) FROM matches_excluded").fetchone()[0]
    by_reason = dict(conn.execute("SELECT excluded_reason || ' (' || excluded_scope || ')', COUNT(*) "
                                  "FROM matches_excluded GROUP BY 1").fetchall())
    by_format = dict(conn.execute("SELECT format, COUNT(*) FROM matches_excluded GROUP BY format").fetchall())
    return {"registry_entries": entries, "rows": rows, "by_reason": by_reason, "by_format": by_format}
