"""
fill_database.py — Standalone database builder for MTG Meta Analyzer.

Runs completely outside VS Code. Double-click fill_database.bat to launch.

Steps performed:
  1. Initialize database schema
  2. Download Scryfall card database (~75 MB, skipped if fresh)
  3. Backfill MTGTop8: Standard, Pioneer, Modern (3 years of history)
  4. Scrape MTGDecks: Standard, Pioneer, Modern (recent pages)
  5. Enrich card data via Scryfall lookups
  6. Normalize archetype names

Progress is printed to the terminal throughout. Safe to re-run — all
scrapers skip events already in the database.
"""

import sys
import io
import os
import json
import time
from datetime import datetime

# Force UTF-8 output on Windows so event names with special characters don't crash
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure the project root is on sys.path regardless of where the script is called from
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(text):
    width = 60
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)


def _section(text):
    print()
    print(f"-- {text} " + "-" * max(0, 55 - len(text)))


def _elapsed(start):
    s = int(time.time() - start)
    m, s = divmod(s, 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def _db_counts():
    """Return (events, decks) totals from the active database."""
    try:
        from db.database import get_connection
        with get_connection() as conn:
            events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            decks  = conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]
        return events, decks
    except Exception:
        return 0, 0


# ---------------------------------------------------------------------------
# Step 1 — DB init
# ---------------------------------------------------------------------------

def step_init():
    _banner("STEP 1/6 — Initializing database")
    from db.database import init_db
    init_db()
    events, decks = _db_counts()
    print(f"  Database ready.  Current: {events:,} events, {decks:,} decks.")


# ---------------------------------------------------------------------------
# Step 2 — Scryfall download
# ---------------------------------------------------------------------------

def step_scryfall_download():
    _banner("STEP 2/6 — Scryfall card database")
    from scrapers.scryfall import download_bulk_data, _bulk_is_fresh, BULK_PATH
    if _bulk_is_fresh():
        age_days = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(BULK_PATH))).days
        print(f"  Scryfall database is fresh ({age_days}d old) — skipping download.")
    else:
        print("  Downloading Scryfall oracle cards (~75 MB)...")
        t = time.time()
        download_bulk_data(force=False)
        print(f"  Download complete ({_elapsed(t)}).")


# ---------------------------------------------------------------------------
# Load user preferences
# ---------------------------------------------------------------------------

def _load_formats():
    """Read selected formats from preferences.json, default to standard only."""
    prefs_path = os.path.join(_ROOT, "data", "preferences.json")
    try:
        if os.path.exists(prefs_path):
            with open(prefs_path, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            fmts = prefs.get("formats", ["standard"])
            if fmts:
                return fmts
    except Exception:
        pass
    return ["standard"]


# ---------------------------------------------------------------------------
# Step 3 — MTGTop8 backfill
# ---------------------------------------------------------------------------

def step_mtgtop8_backfill():
    BACKFILL_FORMATS = _load_formats()
    _banner("STEP 3/6 — MTGTop8 historical backfill")
    print(f"  Formats: {', '.join(BACKFILL_FORMATS)}")
    print("  Scrapes 3 years of tournament history. Safe to re-run (skips existing events).")
    print("  This is the slowest step — expect 30-90 minutes per format.")

    from db.database import init_db
    from scrapers.backfill import run_backfill

    init_db()
    t_total = time.time()

    for fmt in BACKFILL_FORMATS:
        _section(f"MTGTop8 backfill: {fmt.upper()}")
        t = time.time()
        before_events, before_decks = _db_counts()
        try:
            run_backfill(format_name=fmt)
        except KeyboardInterrupt:
            print("\n  [interrupted] Stopping backfill. Progress saved.")
            raise
        except Exception as e:
            print(f"  [error] {fmt} backfill failed: {e}")
            continue
        after_events, after_decks = _db_counts()
        added_e = after_events - before_events
        added_d = after_decks  - before_decks
        print(f"  {fmt.upper()} done in {_elapsed(t)}: +{added_e} events, +{added_d} decks")

    print(f"\n  MTGTop8 backfill complete ({_elapsed(t_total)} total).")


# ---------------------------------------------------------------------------
# Step 4 — MTGDecks scrape
# ---------------------------------------------------------------------------

def step_mtgdecks():
    MTGDECKS_FORMATS = _load_formats()
    MTGDECKS_PAGES   = 5
    _banner("STEP 4/6 — MTGDecks recent events")
    print(f"  Formats: {', '.join(MTGDECKS_FORMATS)}  |  Pages per format: {MTGDECKS_PAGES}")
    print("  Complements MTGTop8 with additional recent tournament data.")

    from scrapers.mtgdecks import run_scraper

    t_total = time.time()

    for fmt in MTGDECKS_FORMATS:
        _section(f"MTGDecks: {fmt.upper()}")
        t = time.time()
        before_events, before_decks = _db_counts()
        try:
            run_scraper(format_name=fmt, pages=MTGDECKS_PAGES, min_players=32)
        except KeyboardInterrupt:
            print("\n  [interrupted] Stopping MTGDecks scrape. Progress saved.")
            raise
        except Exception as e:
            print(f"  [error] {fmt} MTGDecks scrape failed: {e}")
            continue
        after_events, after_decks = _db_counts()
        added_e = after_events - before_events
        added_d = after_decks  - before_decks
        print(f"  {fmt.upper()} done in {_elapsed(t)}: +{added_e} events, +{added_d} decks")

    print(f"\n  MTGDecks scrape complete ({_elapsed(t_total)} total).")


# ---------------------------------------------------------------------------
# Step 5 — Scryfall enrichment
# ---------------------------------------------------------------------------

def step_enrich():
    _banner("STEP 5/6 — Scryfall card enrichment")
    print("  Looks up oracle text, mana cost, type, legality for all unenriched cards.")
    print("  Uses local bulk JSON first (fast), falls back to live API only for misses.")

    from scrapers.scryfall import enrich_cards, enrich_stats
    t = time.time()
    before = enrich_stats()
    print(f"  Before: {before.get('enriched', 0):,} enriched / {before.get('total', 0):,} total cards")
    enrich_cards(force=False)
    after = enrich_stats()
    newly = after.get('enriched', 0) - before.get('enriched', 0)
    print(f"  After:  {after.get('enriched', 0):,} enriched / {after.get('total', 0):,} total cards")
    print(f"  Enriched {newly:,} new cards in {_elapsed(t)}.")


# ---------------------------------------------------------------------------
# Step 6 — Archetype normalization
# ---------------------------------------------------------------------------

def step_normalize():
    _banner("STEP 6/6 — Archetype name normalization")
    print("  Applies alias table to standardize archetype names across sources.")
    print('  e.g. "UR Prowess" -> "Izzet Prowess"')

    from analysis.archetypes import apply_normalization
    t = time.time()
    try:
        result = apply_normalization(dry_run=False, fuzzy=False)
        if isinstance(result, dict):
            updated = result.get('updated', 0)
            print(f"  Normalized {updated:,} deck records in {_elapsed(t)}.")
        else:
            print(f"  Normalization complete ({_elapsed(t)}).")
    except Exception as e:
        print(f"  [error] Normalization failed: {e}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(t_start):
    _banner("COMPLETE")
    events, decks = _db_counts()
    print(f"  Total events in database : {events:,}")
    print(f"  Total decks in database  : {decks:,}")
    print(f"  Total time               : {_elapsed(t_start)}")
    print()
    print("  Launch the GUI:  python run_gui.py")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t_start = time.time()

    print()
    print("=" * 60)
    print("  MTG META ANALYZER — DATABASE BUILDER")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()
    print("  Press Ctrl+C at any time to stop. Progress is saved.")
    print("  Re-running this script is safe — existing data is skipped.")

    try:
        step_init()
        step_scryfall_download()
        step_mtgtop8_backfill()
        step_mtgdecks()
        step_enrich()
        step_normalize()
        print_summary(t_start)
    except KeyboardInterrupt:
        print(f"\n\n  Stopped by user after {_elapsed(t_start)}.")
        events, decks = _db_counts()
        print(f"  Database contains {events:,} events, {decks:,} decks.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n  Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
