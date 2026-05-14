"""One-shot backfill: link historical match_log rows to saved_decks.

Can be re-run manually via `python -m scripts.backfill_match_log_decks`.
Idempotent -- already-resolved rows are skipped.

Strategy:
  - For each row where my_deck_id IS NULL:
      candidates = saved_decks where archetype matches my_deck string
                   AND format matches AND created_at within +/- 90 days
                   of match_log.event_date
      if exactly 1 candidate -> auto-link, backfill_status='auto'
                              -> upsert deck_variants from current saved_decks state
                                 (approximate; not the as-of-match snapshot)
      else                   -> backfill_status='orphan', my_deck_id stays NULL

Returns: {'auto': n, 'orphan': m, 'skipped_already_resolved': k}.
"""
from __future__ import annotations

import datetime as _dt
from db.database import get_connection
from db.deck_variants import upsert_variant
from db.saved_decks import get_decks
from analysis.archetypes import pre_normalize

_DATE_WINDOW_DAYS = 90


def _parse_date(s: str) -> _dt.date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _within_window(a: str, b: str) -> bool:
    da, db_ = _parse_date(a), _parse_date(b)
    if da is None or db_ is None:
        return True  # missing date -> permissive, don't exclude
    return abs((da - db_).days) <= _DATE_WINDOW_DAYS


def _candidates_for(my_deck_str: str, format_name: str, event_date: str,
                    all_decks: list[dict]) -> list[dict]:
    target = pre_normalize(my_deck_str).lower() if my_deck_str else ""
    if not target:
        return []
    return [
        d for d in all_decks
        if d.get("format", "").lower() == format_name.lower()
        and pre_normalize(d.get("archetype", "")).lower() == target
        and _within_window(d.get("created_at", ""), event_date)
    ]


def run() -> dict:
    summary = {"auto": 0, "orphan": 0, "skipped_already_resolved": 0}
    all_decks = get_decks()
    with get_connection() as conn:
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute(
            "SELECT * FROM match_log WHERE my_deck_id IS NULL "
            "AND (backfill_status IS NULL OR backfill_status IN ('live','orphan'))"
        ).fetchall()

    for row in rows:
        cands = _candidates_for(
            my_deck_str=row["my_deck"],
            format_name=row["format"] or "standard",
            event_date=row["event_date"] or "",
            all_decks=all_decks,
        )
        if len(cands) == 1:
            deck = cands[0]
            variant_hash = upsert_variant(
                deck_id=deck["id"],
                mainboard=deck.get("mainboard", {}) or {},
                sideboard=deck.get("sideboard", {}) or {},
                won=(row["result"] == "win"),
            )
            with get_connection() as conn:
                conn.execute(
                    "UPDATE match_log SET my_deck_id=?, my_variant_hash=?, "
                    "backfill_status='auto' WHERE id=?",
                    (deck["id"], variant_hash, row["id"]),
                )
            summary["auto"] += 1
        else:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE match_log SET backfill_status='orphan' WHERE id=?",
                    (row["id"],),
                )
            summary["orphan"] += 1
    return summary


if __name__ == "__main__":
    s = run()
    print(f"Backfill complete: auto={s['auto']} orphan={s['orphan']}")
