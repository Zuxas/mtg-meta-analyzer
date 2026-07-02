#!/usr/bin/env python3
"""Sync harness session-file match records into match_log.

Reads `harness/knowledge/mtg/mtga-session-YYYY-MM-DD.md` files,
parses their Match Results sections, and upserts into
`mtg_meta.db:match_log`. Idempotent on re-run.

Usage:
    python scripts/sync_session_to_matchlog.py
    python scripts/sync_session_to_matchlog.py --dry-run
    python scripts/sync_session_to_matchlog.py --sessions-dir <path>
    python scripts/sync_session_to_matchlog.py --default-my-deck "Dimir Midrange"

## KNOWN AMBIGUITY — NOT AUTO-RESOLVED

The 3 pre-existing rows in match_log as of 2026-04-24 are tagged
`my_deck='Dimir Tempo'`. Session files tagged from fresh MTGA runs
may use a different name (e.g., 'Dimir Midrange'). This script
**preserves my_deck values as-given and does NOT auto-normalize**
the naming collision. Rationale: if Dimir Tempo and Dimir Midrange
are genuinely different archetypes (tempo shell vs midrange shell),
silent merge would corrupt the data.

Future queries wanting aggregate WR across both names must explicitly
union: `WHERE my_deck IN ('Dimir Midrange', 'Dimir Tempo')`.

If Jermey remembers Dimir Tempo == Dimir Midrange (same archetype,
different era label), a one-off UPDATE can normalize retroactively:
`UPDATE match_log SET my_deck='Dimir Midrange' WHERE my_deck='Dimir Tempo';`

## Design notes

- Dedup: (event_date, opp_name, my_deck, arena_match_id) tuple.
  Session files don't contain arena_match_id, so dedup falls back
  to (event_date, opp_name, my_deck) for session-sourced rows.
  Any row with an arena_match_id takes precedence over a matching
  session-only row on the same (date, opp, deck) tuple.
- Schema-aware: reads PRAGMA table_info at startup, validates the
  columns the script assumes exist, exits loudly if schema drifted.
- NOT NULL columns with default='' are populated with '' when
  session file doesn't carry the info.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# Defaults — override via CLI
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from db.database import DB_PATH as CENTRAL_DB_PATH
# CENTRAL_DB_PATH already resolves env var MTG_META_DB > config.ini > fallback
DEFAULT_DB = Path(CENTRAL_DB_PATH)
DEFAULT_SESSIONS = Path(_os.environ.get(
    "HARNESS_SESSIONS",
    Path(__file__).resolve().parent.parent.parent / "harness" / "knowledge" / "mtg"
))

# Expected match_log columns (schema snapshot 2026-04-24). If schema
# drifts, exit rather than silently write wrong rows.
EXPECTED_COLUMNS = {
    "id", "event_name", "event_date", "format", "round", "my_deck",
    "opp_deck", "opp_name", "result", "play_draw", "g1_result",
    "g2_result", "g3_result", "notes", "created_at", "arena_match_id",
    "swap_notes", "swap_verdict",
}

# Regex for match-line format from mtga_log_parser output.
# Example line: "- [W] vs urbae (W/W) OTD ù Direct Game (Bo3)"
# Groups: result, opp_name, opp_colors, play_draw, rest (event + format)
MATCH_LINE = re.compile(
    r"^-\s*\[([WL])\]\s+vs\s+(\S+)\s+"
    r"\(([^)]+)\)"                      # opp colors e.g. W/W
    r"(?:\s+(OTP|OTD))?"                # play/draw optional
    r"\s*[^\w(]*"                        # the 'ù' separator or variants
    r"(.*?)"                             # event name prefix
    r"\s+\((Bo[13])\)\s*$"              # Bo1 or Bo3 suffix
)


def parse_session_file(path: Path) -> dict:
    """Extract frontmatter + match-results from a session .md file."""
    txt = path.read_text(encoding="utf-8-sig")
    # Frontmatter
    meta = {}
    if txt.lstrip().startswith("title:") or txt.lstrip().startswith("---"):
        # Loose parse — the files have inconsistent YAML fencing
        for line in txt.split("---", 2)[0].splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip().strip('"').strip("'")
    # Date range
    date_m = re.search(r"Date range:\s*(\d{4}-\d{2}-\d{2})", txt)
    event_date = date_m.group(1) if date_m else meta.get("last_updated", "")
    # Match lines
    matches = []
    in_results = False
    for raw in txt.splitlines():
        line = raw.rstrip()
        if line.startswith("## Match Results"):
            in_results = True
            continue
        if in_results and line.startswith("## "):
            break
        if in_results and line.startswith("- "):
            m = MATCH_LINE.match(line)
            if not m:
                # Line doesn't match canonical format — record raw
                # for debugging, don't crash
                matches.append({"_raw_unparsed": line, "event_date": event_date})
                continue
            result_char, opp_name, opp_colors, play_draw, event_prefix, bo = m.groups()
            matches.append({
                "event_date": event_date,
                "opp_name": opp_name,
                "opp_colors": opp_colors,
                "play_draw": {"OTP": "play", "OTD": "draw", None: ""}[play_draw],
                "event_name": f"{event_prefix.strip()} ({bo})" if event_prefix.strip() else bo,
                "result": {"W": "win", "L": "loss"}[result_char],
                "bo": bo,
            })
    return {
        "source_file": path.name,
        "last_updated": meta.get("last_updated", ""),
        "matches": matches,
    }


def schema_check(cur) -> None:
    cols = {r[1] for r in cur.execute("PRAGMA table_info(match_log)")}
    missing = EXPECTED_COLUMNS - cols
    extra = cols - EXPECTED_COLUMNS
    if missing:
        print(f"ERROR: match_log schema missing columns: {missing}", file=sys.stderr)
        sys.exit(2)
    if extra:
        print(f"  [note] match_log has {len(extra)} extra columns not expected by "
              f"this script: {sorted(extra)}. Writing will work but those columns "
              f"will keep their defaults.", file=sys.stderr)


def existing_keys(cur) -> set:
    """Return the set of (event_date, opp_name) pairs already in match_log.

    Deliberately conservative: we dedup on (date, opp) rather than
    (date, opp, my_deck) because session files don't tag my_deck
    reliably — the 'Dimir Tempo' vs 'Dimir Midrange' naming collision
    called out in the header would cause false-new-row duplicates if
    my_deck were part of the key. Trade-off: if the same player played
    the same opponent twice on the same day with different decks,
    the second match would get skipped. That's unusual enough in real
    sessions to accept; the alternative (duplicates on ambiguous
    my_deck) is a worse failure mode.
    """
    return {
        (r[0], r[1])
        for r in cur.execute("SELECT event_date, opp_name FROM match_log")
    }


def build_row(match: dict, my_deck: str, fmt: str) -> dict:
    """Build a match_log row dict from a parsed session-file match."""
    now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    # Map session g1 result from the top-line result (Bo1 = g1 only)
    g1 = match["result"]
    return {
        "event_name":     match.get("event_name", ""),
        "event_date":     match["event_date"],
        "format":         fmt,
        "round":          0,
        "my_deck":        my_deck,
        "opp_deck":       "",                       # archetype unknown from session file
        "opp_name":       match["opp_name"],
        "result":         match["result"],
        "play_draw":      match.get("play_draw", ""),
        "g1_result":      g1 if match.get("bo") == "Bo1" else "",
        "g2_result":      "",
        "g3_result":      "",
        "notes":          f"synced from {match.get('source_file','session file')}; "
                          f"opp_colors={match.get('opp_colors','')}",
        "created_at":     now,
        "arena_match_id": None,   # session files don't carry it
        "swap_notes":     "",
        "swap_verdict":   "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS))
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be upserted without writing.")
    ap.add_argument("--default-my-deck", default="",
                    help="my_deck value for session-file rows that don't carry one. "
                         "PRESERVED AS-GIVEN (see header for naming-collision note).")
    ap.add_argument("--format", default="standard")
    args = ap.parse_args()

    sessions_dir = Path(args.sessions_dir)
    files = sorted(sessions_dir.glob("mtga-session-*.md"))
    if not files:
        print(f"No session files under {sessions_dir}")
        return 0

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    schema_check(cur)

    mode = "DRY RUN" if args.dry_run else "WRITE"
    print(f"=== SYNC {mode} — {len(files)} session files, db={args.db}")
    print(f"     default-my-deck = {args.default_my_deck!r} (preserved as-given)")

    seen_keys = existing_keys(cur)   # seeded from DB; grows per upsert to dedup batch
    upsert_rows = []
    skipped_db_existing = 0
    skipped_batch_duplicate = 0
    skipped_unparsed = 0
    parsed_total = 0
    for f in files:
        data = parse_session_file(f)
        for m in data["matches"]:
            if "_raw_unparsed" in m:
                skipped_unparsed += 1
                print(f"  [UNPARSED] {f.name}: {m['_raw_unparsed']}")
                continue
            parsed_total += 1
            key = (m["event_date"], m["opp_name"])
            my_deck = args.default_my_deck
            if key in seen_keys:
                # Could be DB-existing or earlier-in-batch; either way, skip
                if all(key != (r["event_date"], r["opp_name"]) for r in upsert_rows):
                    skipped_db_existing += 1
                else:
                    skipped_batch_duplicate += 1
                continue
            row = build_row(m, my_deck, args.format)
            row["_source_file"] = f.name
            upsert_rows.append(row)
            seen_keys.add(key)  # within-batch dedup

    print()
    print(f"Parsed:                  {parsed_total} match records across {len(files)} files")
    print(f"Skipped (DB existing):   {skipped_db_existing}  [already in match_log]")
    print(f"Skipped (batch dup):     {skipped_batch_duplicate}  [same (date, opp) within this run]")
    print(f"Skipped (unparsed):      {skipped_unparsed}")
    print(f"Would upsert:            {len(upsert_rows)}")

    for r in upsert_rows[:10]:
        print(f"  + {r['event_date']}  vs {r['opp_name']:20s} "
              f"my_deck={r['my_deck']!r:20s}  result={r['result']:5s}  "
              f"from {r['_source_file']}")

    if args.dry_run:
        print("\n[DRY RUN] No writes. Re-run without --dry-run to commit.")
        return 0

    if not upsert_rows:
        print("\nNothing to upsert. Exiting.")
        return 0

    # Commit
    cols_to_insert = [c for c in EXPECTED_COLUMNS if c != "id"]
    placeholders = ", ".join("?" for _ in cols_to_insert)
    sql = f"INSERT INTO match_log ({', '.join(cols_to_insert)}) VALUES ({placeholders})"
    for r in upsert_rows:
        values = [r[c] for c in cols_to_insert]
        cur.execute(sql, values)
    conn.commit()
    print(f"\nWrote {len(upsert_rows)} new rows to match_log.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
