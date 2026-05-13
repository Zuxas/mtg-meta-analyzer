"""
scripts/backfill_prowess_primer_notes.py

One-shot script: parse the Worldly Council Izzet Prowess primer text file
and update saved_sb_plans.notes for the Tokyo deck (id=17) with the
matchup-specific play-pattern prose from the primer.

Replaces the boilerplate "Re-imported from canonical CSV..." notes I
generated from the SB sheet import with the actual primer guidance.

The Print SB Guide button surfaces the notes in each matchup tile, so
this is what makes the printable card actually useful for tournament prep.
"""

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mtg_meta.db"
DEFAULT_DECK_ID = 17  # Izzet Prowess (Worldly Council / Tokyo) -- RC Cincinnati 2026-05-29

# Primer text path comes from --primer arg or PROWESS_PRIMER_PATH env var.
# Reference shape (don't hardcode user-specific paths in source):
#   <Desktop>/A Primer on Izzet Prowess.txt
# The Worldly Council primer is a paid product; users supply their own copy.

# Primer-matchup-name -> saved-plan opponent_archetype (sometimes differs)
PRIMER_TO_SAVED = {
    "Mono-Green Landfall":           ["Mono Green Landfall"],
    "Green-White Landfall":          ["GW Landfall", "GW Cub"],
    "Izzet Prowess, the crab mirror": ["Izzet Prowess", "Stallion Prowess", "Cosmos Prowess"],
    "Spellemental":                  ["Izzet Spellementals"],
    "Izzet Lessons":                 ["Izzet Lessons (Stormchaser)", "Izzet Lessons (no Stormchaser)"],
    "UW High Noon":                  ["UW High Noon", "Jeskai Control"],  # Jeskai Tablet variants overlap
    "Kona Omniscience Combo":        ["Kona Omniscience Combo"],
    "Dimir Excruciator (Demon)":     ["Dimir Excruciator"],
    "4c Elemental":                  ["4c Elemental"],
    "Mardu Discard / RB Monument":   ["Mardu Discard / RB Monument"],
    "UW Momo":                       ["UW Momo"],
    "GW Cub":                        ["GW Cub"],
}


def parse_primer_sections(text: str) -> dict:
    """Return {matchup_name: prose_excerpt} from the primer text."""
    sections = re.split(
        r'(?m)^Sideboard guide, analysis matchup per matchup\s*$', text
    )
    out = {}
    for s in sections[1:]:
        lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
        if not lines:
            continue
        name = lines[0]
        if name in ("A word of caution", "Printable sideboard guide"):
            continue
        # Collect prose until we hit a SB-plan delimiter or "Tips :"
        prose_lines = []
        for ln in lines[1:]:
            if re.match(r'^(On The (Play|Draw)|[\-\+]\d|Printable|Tips\s*:)\b', ln, re.I):
                break
            prose_lines.append(ln)
        if prose_lines:
            out[name] = " ".join(prose_lines)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--primer", help="Path to the primer .txt file "
                    "(default: $PROWESS_PRIMER_PATH env var)")
    ap.add_argument("--deck-id", type=int, default=DEFAULT_DECK_ID,
                    help=f"saved_decks.id to update (default: {DEFAULT_DECK_ID})")
    args = ap.parse_args()

    primer_path_str = args.primer or os.environ.get("PROWESS_PRIMER_PATH", "")
    if not primer_path_str:
        print("ERROR: --primer <path> or PROWESS_PRIMER_PATH env var required.")
        print("(The primer is a paid product; supply your own copy of the .txt.)")
        sys.exit(2)
    primer_path = Path(primer_path_str).expanduser()
    if not primer_path.exists():
        print(f"Primer not found: {primer_path}")
        sys.exit(1)
    deck_id = args.deck_id

    text = primer_path.read_text(encoding="utf-8", errors="replace")
    primer = parse_primer_sections(text)
    print(f"Parsed {len(primer)} primer matchup sections")

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    # Get all saved plans for the deck
    plans = con.execute(
        "SELECT id, opponent_archetype, notes FROM saved_sb_plans WHERE deck_id = ?",
        (deck_id,),
    ).fetchall()
    print(f"Loaded {len(plans)} saved SB plans for deck {deck_id}")

    # Build reverse mapping: saved_opponent -> primer_section
    saved_to_primer = {}
    for primer_name, saved_names in PRIMER_TO_SAVED.items():
        for sn in saved_names:
            saved_to_primer.setdefault(sn, primer_name)

    updated = 0
    skipped = 0
    for plan in plans:
        opp = plan["opponent_archetype"] or ""
        primer_name = saved_to_primer.get(opp)
        if not primer_name:
            print(f"  SKIP (no primer mapping): {opp}")
            skipped += 1
            continue
        prose = primer.get(primer_name)
        if not prose:
            print(f"  SKIP (primer section empty): {primer_name}")
            skipped += 1
            continue

        # Compose new notes: primer prose + preserve relevant existing notes
        existing = (plan["notes"] or "").strip()
        # Drop the boilerplate import noise; keep anything else (e.g. Nick's overrides)
        if existing and not existing.startswith("Re-imported from canonical CSV"):
            new_notes = f"{prose}\n\n---\nPrior notes:\n{existing}"
        else:
            new_notes = prose

        con.execute(
            "UPDATE saved_sb_plans SET notes = ? WHERE id = ?",
            (new_notes, plan["id"]),
        )
        updated += 1
        print(f"  UPD {opp:<36} <- {primer_name}")

    con.commit()
    con.close()
    print(f"\nDone. Updated {updated} plans, skipped {skipped}.")


if __name__ == "__main__":
    main()
