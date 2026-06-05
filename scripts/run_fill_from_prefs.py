"""
scripts/run_fill_from_prefs.py

Reads data/preferences.json and runs the background scrape pipeline
only for the formats the user has selected.

Called by background_fill.bat instead of hardcoded format lists.
Safe to run directly: python scripts/run_fill_from_prefs.py
"""
import sys
import io
import os
import json
import subprocess
import datetime as _dt

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PREFS = os.path.join(_ROOT, "data", "preferences.json")

# Formats that get MTGMelee scrapes regardless of user preference
# (real match data is format-agnostic and always useful)
_MELEE_ALWAYS = ["legacy", "pauper"]


def load_formats():
    try:
        if os.path.exists(_PREFS):
            with open(_PREFS, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            fmts = prefs.get("formats", [])
            if fmts:
                return fmts
    except Exception as e:
        print(f"[prefs] Could not read preferences: {e} — defaulting to Standard")
    return ["standard"]


def run(cmd, label):
    print(f"\n-- {label} " + "-" * max(0, 55 - len(label)))
    result = subprocess.run(
        [sys.executable] + cmd.split(),
        cwd=_ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode != 0:
        print(f"  [warn] exited with code {result.returncode}")


def main():
    formats = load_formats()
    print(f"[prefs] Active formats: {', '.join(formats)}")

    # MTGTop8 — selected formats only
    for fmt in formats:
        run(f"main.py --format {fmt} --pages 2 --max-events 50",
            f"MTGTop8 — {fmt}")

    # MTGDecks — auto-pull DISABLED 2026-06-04 per user request.
    # Manual paths still available: fill_database.bat (full rebuild), Settings
    # tab refresh button, Matchup Data tab "scrape" action.
    # To re-enable: restore the M/W/F gate (was `MTGDECKS_DAYS = (0, 2, 4)`).
    today_dow = _dt.date.today().weekday()   # Mon=0, Sun=6 (still used by Untapped block below)
    print("\n-- MTGDecks SKIPPED (auto-pull disabled) --")

    # MTGMelee — selected formats + always-on extras
    melee_formats = list(dict.fromkeys(formats + _MELEE_ALWAYS))
    for fmt in melee_formats:
        run(f"-m scrapers.mtgmelee_scraper --format {fmt} --pages 3",
            f"MTGMelee — {fmt}")

    # Spicerack — RCQs, Store Championships, large paper events
    spice_formats = [f for f in formats if f.lower() in
                     ("modern", "standard", "pioneer", "legacy", "pauper")]
    for fmt in spice_formats:
        run(f"-m scrapers.spicerack_scraper --format {fmt} --days 30 --top-n 8",
            f"Spicerack RCQs -- {fmt}")

    # Scryfall enrichment (always)
    run("-m scrapers.scryfall", "Scryfall enrichment")

    # User's Arena games (always; reads local Player.log). Wired into the
    # daily pipeline 2026-05-14 -- previously manual-CLI-only, which meant
    # ranked matches never showed up in Match Log until the user remembered
    # to run the parser. Failure is non-fatal -- the user may not have MTGA
    # running on this machine.
    try:
        from scrapers.mtga_log_parser import (
            parse_log_file, save_matches_to_db, PLAYER_LOG, PLAYER_PREV_LOG,
        )
        all_matches = []
        for log_path in (PLAYER_LOG, PLAYER_PREV_LOG):
            if not os.path.exists(log_path):
                continue
            try:
                all_matches.extend(parse_log_file(log_path))
            except Exception as e:
                print(f"[MTGA log] parse error on {log_path}: {e}")
        if all_matches:
            for fmt in formats:
                n = save_matches_to_db(all_matches, format_name=fmt)
                if n:
                    print(f"[MTGA log] {fmt}: {n} new matches imported")
        else:
            print("[MTGA log] no Player.log found or no matches parsed")
    except Exception as e:
        print(f"[MTGA log] importer error: {e}")

    # Rank progression snapshot from MTGA Player.log (always; cheap)
    try:
        from analysis.rank_tracker import capture_current_rank
        result = capture_current_rank(notes="background_fill")
        if result:
            c = result.get("constructed") or {}
            print(f"[MTGA rank] constructed: {c.get('class')} {c.get('level')} "
                  f"({c.get('wins')}-{c.get('losses')})")
        else:
            print("[MTGA rank] no rank data found in Player.log")
    except Exception as e:
        print(f"[MTGA rank] capture error: {e}")

    # Untapped.gg — mythic leaderboard + premium per-archetype data
    # Throttled to Mon/Wed/Fri (~3x/week) to match MTGDecks cadence.
    # Mythic is public/unauthenticated; premium needs session credentials (see UNTAPPED_README).
    UNTAPPED_DAYS = (0, 2, 4)                # Mon, Wed, Fri
    if today_dow in UNTAPPED_DAYS:
        run("-m scrapers.untapped_mythic_scraper --notes background_fill",
            "Untapped mythic leaderboard")
        run("-m scrapers.untapped_premium_scraper",
            "Untapped premium")
        # Per-rank archetype WR for ALL formats (free meta endpoint).
        # Added to pipeline 2026-05-14 -- previously only ran manually.
        run("-m scrapers.untapped_meta_scraper",
            "Untapped meta (per-rank archetype WR)")
        # Bo1 showcase matchup matrix (free endpoint).
        # Added to pipeline 2026-05-14 -- previously only ran manually.
        run("-m scrapers.untapped_matchup_scraper",
            "Untapped matchup matrix")
        # Replay corpus refresh -- pulls upload-log JSON for any short_id
        # in untapped_entries that doesn't yet have a local replay.
        # Throttled to top 50 by matches_count to keep network usage
        # bounded (~50 * 250KB gz = 12.5 MB per M/W/F run).
        # Added to pipeline 2026-05-14 -- previously only ran manually.
        run("-m scrapers.untapped_replay_fetcher --top 50",
            "Untapped replay fetch (top 50)")
        try:
            from scrapers.untapped_match_log_writer import run as _utw_run
            print("[Untapped] Writing match_log rows from replay corpus...")
            n_new = _utw_run()
            print(f"[Untapped] match_log: {n_new} new rows")
        except Exception as e:
            print(f"[Untapped] match_log writer error: {e}")
        try:
            from db.untapped_decklists import populate_for_all_local_replays
            print("[Untapped] Extracting decklists from replay corpus...")
            dl_stats = populate_for_all_local_replays(skip_existing=True)
            print(f"[Untapped] decklists: {dl_stats}")
        except Exception as e:
            print(f"[Untapped] decklist populator error: {e}")
    else:
        day_name = _dt.date.today().strftime("%a")
        print(f"\n-- Untapped SKIPPED (throttled to M/W/F, today is {day_name}) --")

    # Archetype normalization (always)
    run("-m analysis.archetypes --apply", "Archetype normalization")

    # Archive maintenance (always)
    run("-m db.maintenance", "Archive maintenance")

    print("\n[done] Background fill complete.")


if __name__ == "__main__":
    main()
