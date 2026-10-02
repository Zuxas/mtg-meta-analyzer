"""Import / export a sideboard matrix (sb-matrix/1 JSON) <-> saved_sb_plans.

DRY-RUN BY DEFAULT. Nothing is written unless --commit is given.

  Validate a matrix against a plain-text 75 (no DB access at all):
    python scripts/import_sb_matrix.py --matrix data/sb_matrices/X.json --decklist data/sb_matrices/X.txt

  Validate against a saved deck and print the diff vs its current plans (read-only):
    python scripts/import_sb_matrix.py --matrix X.json --deck-id 12

  Write it (all-or-nothing, one transaction):
    python scripts/import_sb_matrix.py --matrix X.json --deck-id 12 --commit

  Save the .txt 75 as a new saved deck AND import its plans (needs --commit):
    python scripts/import_sb_matrix.py --matrix X.json --decklist X.txt --save-deck "Izzet Prowess (locked)" --commit

  Render a saved deck's plans (or the matrix itself) as an HTML matrix:
    python scripts/import_sb_matrix.py --deck-id 12 --html out.html
    python scripts/import_sb_matrix.py --matrix X.json --decklist X.txt --html out.html

  Export a saved deck's plans back to matrix JSON:
    python scripts/import_sb_matrix.py --deck-id 12 --export out.json

Exit codes: 0 ok, 1 validation failed (nothing written), 2 usage error.
Spec: harness/specs/2026-09-26-session-assets-intake.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db.helpers import force_utf8_stdio  # noqa: E402
from analysis import sb_matrix as sbm    # noqa: E402


def _load_matrix(path: str) -> sbm.Matrix:
    with open(path, encoding="utf-8") as fh:
        return sbm.parse_matrix(json.load(fh))


def _load_decklist(path: str) -> tuple[dict, dict]:
    with open(path, encoding="utf-8") as fh:
        return sbm.parse_decklist(fh.read())


def main(argv=None) -> int:
    force_utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--matrix", help="sb-matrix/1 JSON file")
    ap.add_argument("--decklist", help="plain-text 75 ('4 Card', 'Sideboard' header)")
    ap.add_argument("--deck-id", type=int, help="saved_decks.id to validate against / write to")
    ap.add_argument("--save-deck", metavar="NAME", help="save --decklist as a new saved deck (needs --commit)")
    ap.add_argument("--commit", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--html", metavar="OUT", help="write an HTML matrix")
    ap.add_argument("--export", metavar="OUT", help="export the deck's saved plans as matrix JSON")
    a = ap.parse_args(argv)

    if not a.matrix and not (a.deck_id and (a.html or a.export)):
        ap.error("give --matrix, or --deck-id with --html/--export")
    if a.deck_id and a.save_deck:
        ap.error("--deck-id and --save-deck are exclusive")
    if a.save_deck and not a.decklist:
        ap.error("--save-deck needs --decklist")
    if a.commit and not (a.deck_id or a.save_deck):
        ap.error("--commit needs a target: --deck-id or --save-deck")

    deck = None
    existing: list[dict] = []
    if a.deck_id:
        from db import saved_decks
        deck = saved_decks.get_deck(a.deck_id)
        if deck is None:
            print(f"ERROR: saved deck id {a.deck_id} not found")
            return 2
        main_, side_ = deck["mainboard"], deck["sideboard"]
        existing = saved_decks.get_sb_plans(a.deck_id)
        if a.decklist:
            fm, fs = _load_decklist(a.decklist)
            if sbm.deck_fingerprint(fm, fs) != sbm.deck_fingerprint(main_, side_):
                print("WARNING: --decklist differs from the saved deck; validating against the SAVED deck")
    elif a.decklist:
        main_, side_ = _load_decklist(a.decklist)
    else:
        print("ERROR: need --decklist or --deck-id to validate against")
        return 2

    fp = sbm.deck_fingerprint(main_, side_)
    title = (deck or {}).get("name") or os.path.basename(a.decklist or "deck")
    print(f"Deck: {title} | main {sum(main_.values())} / side {sum(side_.values())} | fp {fp}")

    rows = existing
    if a.matrix:
        try:
            matrix = _load_matrix(a.matrix)
        except sbm.MatrixError as e:
            print(f"INVALID matrix ({len(e.problems)} problem(s)):")
            for p in e.problems:
                print(f"  - {p}")
            return 1
        resolved, problems = sbm.resolve_against_deck(matrix, main_, side_)
        if problems:
            print(f"INVALID against this 75 ({len(problems)} problem(s)); nothing written:")
            for p in problems:
                print(f"  - {p}")
            return 1
        source = f"{os.path.basename(a.matrix)}: {matrix.source}".strip()
        rows = sbm.to_plan_rows(resolved, fp, source)
        print(f"OK: {len(rows)} matchups validated, every column balanced.")
        for line in sbm.diff_rows(existing, rows):
            print("  " + line)

        if a.commit:
            from db import saved_decks
            deck_id = a.deck_id
            if a.save_deck:
                d = matrix.deck or {}
                deck_id = saved_decks.save_deck(
                    name=a.save_deck, format_name=d.get("format", ""),
                    archetype=d.get("archetype", ""), mainboard=main_, sideboard=side_,
                    notes=f"Imported by import_sb_matrix.py from {os.path.basename(a.decklist)}")
                print(f"Saved deck id {deck_id}: {a.save_deck}")
            n = saved_decks.save_sb_plans_atomic(deck_id, rows)
            print(f"COMMITTED {n} plan(s) to deck id {deck_id}.")
            rows = saved_decks.get_sb_plans(deck_id)
        else:
            print("DRY RUN: nothing written (add --commit).")

    if a.deck_id and not a.matrix:
        stale = [r["opponent_archetype"] for r in rows if sbm.plan_is_stale(r, main_, side_)]
        if stale:
            print(f"STALE ({len(stale)}): imported against a different 75: {', '.join(stale)}")

    if a.export:
        doc = sbm.plans_to_matrix(rows, source=f"export of saved deck {a.deck_id}",
                                  deck={"name": title})
        with open(a.export, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
        print(f"Wrote {a.export} ({len(doc['matchups'])} matchups)")
    if a.html:
        page = sbm.render_html(f"{title} - Sideboard Matrix", main_, side_, rows,
                               subtitle=f"Red = out of the main, green = in from the board. Deck fp {fp}.")
        with open(a.html, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(page)
        print(f"Wrote {a.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
