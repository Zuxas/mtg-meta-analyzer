"""
scripts/backfill_fingerprints.py

Populate event_fingerprint and deck_fingerprint for existing rows that
currently have NULL values in the active and/or archive databases.

Resume-safe: only touches rows WHERE fingerprint IS NULL, so an interrupted
run can be restarted with the exact same command — already-processed rows
are skipped automatically.

Usage:
    python scripts/backfill_fingerprints.py              # both DBs
    python scripts/backfill_fingerprints.py --active-only
    python scripts/backfill_fingerprints.py --archive-only
    python scripts/backfill_fingerprints.py --batch-size 1000
    python scripts/backfill_fingerprints.py --dry-run    # count only, no writes

How batching works:
    Events are fetched in chunks of --batch-size ordered by id.
    Each batch UPDATEs the rows and commits.  Because the WHERE clause
    filters on fingerprint IS NULL, the next SELECT naturally returns the
    next unprocessed chunk — no offset arithmetic needed.

    Decks use the same "fetch → bulk card JOIN → update → commit" cycle.
    The card JOIN loads all cards for the entire batch in one query instead
    of one query per deck, keeping I/O proportional to batch count not deck count.
"""

import sys
import os
import time
import argparse
import io
from collections import defaultdict

# Force UTF-8 output on Windows (event names can contain non-ASCII characters)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on sys.path regardless of working directory
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.data_engine.dedup import (
    generate_event_fingerprint,
    generate_event_fingerprint_cs,
    generate_deck_fingerprint,
)
from db.database import (
    get_connection, get_archive_connection, _apply_schema, ARCHIVE_PATH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(text):
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


def _elapsed(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


# ---------------------------------------------------------------------------
# Event backfill
# ---------------------------------------------------------------------------

def _backfill_events(conn, batch_size, dry_run, label, recompute=False):
    """
    Compute and store event_fingerprint (strict — preserves trailing numbers).

    Normal mode (recompute=False): only processes rows WHERE event_fingerprint IS NULL.
    Recompute mode (recompute=True): rewrites ALL rows.  Use this once after the
    fingerprint logic changed from loose (strips trailing numbers) to strict
    (preserves them) to ensure existing data is consistent.
    """
    where_clause = "" if recompute else "WHERE event_fingerprint IS NULL"
    total = conn.execute(
        f"SELECT COUNT(*) FROM events {where_clause}"
    ).fetchone()[0]

    mode_label = "recompute" if recompute else "backfill"
    if total == 0:
        all_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"  [{label}] events fp      : all {all_count} already present")
        return 0

    print(f"  [{label}] events fp      : {total} rows ({mode_label})")
    if dry_run:
        return 0

    updated = 0
    order_clause = "ORDER BY id"
    if recompute:
        # Need OFFSET for recompute since committed rows stay in the result set
        offset = 0
        while True:
            rows = conn.execute(
                f"SELECT id, name, date, format FROM events {order_clause} LIMIT ? OFFSET ?",
                (batch_size, offset),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                fp = generate_event_fingerprint(
                    name=row["name"] or "",
                    date=row["date"] or "",
                    format_name=row["format"] or "",
                )
                conn.execute(
                    "UPDATE events SET event_fingerprint = ? WHERE id = ?",
                    (fp, row["id"]),
                )
            conn.commit()
            offset += len(rows)
            updated += len(rows)
            pct = updated * 100 // total
            print(f"  [{label}] events fp      : {updated:>6} / {total} ({pct:>3}%)",
                  end="\r", flush=True)
            if len(rows) < batch_size:
                break
    else:
        while True:
            rows = conn.execute(
                "SELECT id, name, date, format FROM events "
                "WHERE event_fingerprint IS NULL ORDER BY id LIMIT ?",
                (batch_size,),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                fp = generate_event_fingerprint(
                    name=row["name"] or "",
                    date=row["date"] or "",
                    format_name=row["format"] or "",
                )
                conn.execute(
                    "UPDATE events SET event_fingerprint = ? WHERE id = ?",
                    (fp, row["id"]),
                )
            conn.commit()
            updated += len(rows)
            pct = updated * 100 // total
            print(f"  [{label}] events fp      : {updated:>6} / {total} ({pct:>3}%)",
                  end="\r", flush=True)
            if len(rows) < batch_size:
                break

    print(f"  [{label}] events fp      : {updated:>6} / {total} done          ")
    return updated


def _backfill_event_fp_cs(conn, batch_size, dry_run, label):
    """
    Compute and store event_fingerprint_cs (cross-source — strips trailing numbers).

    Always NULL-only: recompute is not needed since this is a new column and
    the cross-source normalization logic is not expected to change.
    """
    total = conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_fingerprint_cs IS NULL"
    ).fetchone()[0]

    if total == 0:
        all_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"  [{label}] events fp_cs   : all {all_count} already present")
        return 0

    print(f"  [{label}] events fp_cs   : {total} rows need cross-source fingerprints")
    if dry_run:
        return 0

    updated = 0
    while True:
        rows = conn.execute(
            "SELECT id, name, date, format FROM events "
            "WHERE event_fingerprint_cs IS NULL ORDER BY id LIMIT ?",
            (batch_size,),
        ).fetchall()
        if not rows:
            break
        for row in rows:
            fp_cs = generate_event_fingerprint_cs(
                name=row["name"] or "",
                date=row["date"] or "",
                format_name=row["format"] or "",
            )
            conn.execute(
                "UPDATE events SET event_fingerprint_cs = ? WHERE id = ?",
                (fp_cs, row["id"]),
            )
        conn.commit()
        updated += len(rows)
        pct = updated * 100 // total
        print(f"  [{label}] events fp_cs   : {updated:>6} / {total} ({pct:>3}%)",
              end="\r", flush=True)
        if len(rows) < batch_size:
            break

    print(f"  [{label}] events fp_cs   : {updated:>6} / {total} done          ")
    return updated


# ---------------------------------------------------------------------------
# Deck backfill
# ---------------------------------------------------------------------------

def _backfill_decks(conn, batch_size, dry_run, label):
    """
    Compute and store deck_fingerprint for every deck row with a NULL value.

    Card data is loaded via a single JOIN query per batch (not per deck),
    keeping total I/O proportional to the number of batches.

    Decks with zero cards in deck_cards get a fingerprint of empty dicts —
    this is intentional; it marks them as "seen" so future re-runs skip them.
    """
    total = conn.execute(
        "SELECT COUNT(*) FROM decks WHERE deck_fingerprint IS NULL"
    ).fetchone()[0]

    if total == 0:
        print(f"  [{label}] decks  : all {conn.execute('SELECT COUNT(*) FROM decks').fetchone()[0]} fingerprints already present")
        return 0

    print(f"  [{label}] decks  : {total} rows need fingerprints")
    if dry_run:
        return 0

    updated = 0

    while True:
        # Fetch the next batch of deck IDs that still need fingerprinting
        id_rows = conn.execute(
            "SELECT id FROM decks WHERE deck_fingerprint IS NULL ORDER BY id LIMIT ?",
            (batch_size,),
        ).fetchall()

        if not id_rows:
            break

        deck_ids = [r["id"] for r in id_rows]

        # One query loads all cards for every deck in the batch
        placeholders = ",".join("?" * len(deck_ids))
        card_rows = conn.execute(
            f"SELECT dc.deck_id, c.name, dc.quantity, dc.is_sideboard "
            f"FROM deck_cards dc "
            f"JOIN cards c ON c.id = dc.card_id "
            f"WHERE dc.deck_id IN ({placeholders})",
            deck_ids,
        ).fetchall()

        # Group cards into per-deck mainboard / sideboard dicts
        mainboards = defaultdict(dict)
        sideboards = defaultdict(dict)
        for c in card_rows:
            if c["is_sideboard"]:
                sideboards[c["deck_id"]][c["name"]] = c["quantity"]
            else:
                mainboards[c["deck_id"]][c["name"]] = c["quantity"]

        # Compute fingerprint for each deck and UPDATE in place
        for deck_id in deck_ids:
            fp = generate_deck_fingerprint(
                mainboard=mainboards.get(deck_id, {}),
                sideboard=sideboards.get(deck_id, {}),
            )
            conn.execute(
                "UPDATE decks SET deck_fingerprint = ? WHERE id = ?",
                (fp, deck_id),
            )

        conn.commit()
        updated += len(deck_ids)
        pct = updated * 100 // total
        print(
            f"  [{label}] decks  : {updated:>6} / {total} ({pct:>3}%)",
            end="\r", flush=True,
        )

        if len(deck_ids) < batch_size:
            break

    print(f"  [{label}] decks  : {updated:>6} / {total} done          ")
    return updated


# ---------------------------------------------------------------------------
# Per-DB orchestration
# ---------------------------------------------------------------------------

def _process_db(conn, batch_size, dry_run, label, recompute_events=False):
    """Apply schema migrations (adds columns/indexes if absent), then backfill."""
    _apply_schema(conn)  # idempotent — adds fingerprint columns + indexes if missing
    t0 = time.time()
    ev    = _backfill_events(conn, batch_size, dry_run, label, recompute=recompute_events)
    ev_cs = _backfill_event_fp_cs(conn, batch_size, dry_run, label)
    dk    = _backfill_decks(conn, batch_size, dry_run, label)
    return ev + ev_cs, dk, time.time() - t0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Backfill NULL event_fingerprint and deck_fingerprint values.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--active-only", action="store_true",
        help="Only process the active DB (data/mtg_meta.db)",
    )
    parser.add_argument(
        "--archive-only", action="store_true",
        help="Only process the archive DB (data/mtg_archive.db)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=500, metavar="N",
        help="Rows processed and committed per batch (default: 500)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print row counts only — no rows are modified",
    )
    parser.add_argument(
        "--recompute-events", action="store_true",
        help=(
            "Rewrite ALL event_fingerprint values using the current (strict) logic. "
            "Run this once after upgrading from the old loose fingerprint that stripped "
            "trailing numbers. Without this, existing rows keep old loose values and "
            "same-source same-day numbered events may still appear as duplicates."
        ),
    )
    args = parser.parse_args()

    do_active  = not args.archive_only
    do_archive = not args.active_only

    _banner(
        f"Fingerprint Backfill"
        f"  batch={args.batch_size}"
        + ("  DRY RUN" if args.dry_run else "")
        + ("  RECOMPUTE-EVENTS" if args.recompute_events else "")
    )

    total_ev = total_dk = 0
    t_wall = time.time()

    if do_active:
        print("\n[Active DB]")
        conn = get_connection()
        try:
            ev, dk, elapsed = _process_db(
                conn, args.batch_size, args.dry_run, "active",
                recompute_events=args.recompute_events,
            )
        finally:
            conn.close()
        total_ev += ev
        total_dk += dk
        if not args.dry_run:
            print(f"  active DB done in {_elapsed(elapsed)}")

    if do_archive:
        if not os.path.exists(ARCHIVE_PATH):
            print("\n[Archive DB] — file not found, skipping")
        else:
            print("\n[Archive DB]")
            conn = get_archive_connection()
            try:
                ev, dk, elapsed = _process_db(
                    conn, args.batch_size, args.dry_run, "archive",
                    recompute_events=args.recompute_events,
                )
            finally:
                conn.close()
            total_ev += ev
            total_dk += dk
            if not args.dry_run:
                print(f"  archive DB done in {_elapsed(elapsed)}")

    wall = time.time() - t_wall
    _banner("Summary")
    if args.dry_run:
        print("  DRY RUN — no rows were modified")
    else:
        print(f"  Events fingerprinted : {total_ev:>6}")
        print(f"  Decks  fingerprinted : {total_dk:>6}")
        print(f"  Total wall time      : {_elapsed(wall)}")
    print()


if __name__ == "__main__":
    main()
