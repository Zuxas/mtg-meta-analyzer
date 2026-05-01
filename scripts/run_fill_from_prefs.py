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

    # MTGDecks — selected formats only
    for fmt in formats:
        run(f"-m scrapers.mtgdecks --format {fmt} --pages 3",
            f"MTGDecks — {fmt}")

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

    # Archetype normalization (always)
    run("-m analysis.archetypes --apply", "Archetype normalization")

    # Archive maintenance (always)
    run("-m db.maintenance", "Archive maintenance")

    print("\n[done] Background fill complete.")


if __name__ == "__main__":
    main()
