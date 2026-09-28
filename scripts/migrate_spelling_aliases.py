"""Rewrite stored deck labels for the 2026-09-28 spelling-variant aliases ONLY.

`python -m analysis.archetypes --apply` would apply EVERY alias and reformat
ever added (119 label changes on 2026-09-28, some dubious: 'Rakdos Affinity'
-> 'Grixis Affinity', a player name mangled). This touches only labels whose
lowercase form is one of the approved keys below.

  python -m scripts.migrate_spelling_aliases            # dry run
  python -m scripts.migrate_spelling_aliases --commit   # backup-API copy, then write
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.archetypes import ALIASES  # noqa: E402

KEYS_2026_09_28 = (
    "4/5c birthing ritual value", "4c value birthing ritual", "4c control",
    "four-color elemental...", "8 cast", "mono black necrodominance aggro",
    "oops, all spells!", "oops all spells", "death & taxes", "izzet sneak & show",
    "sneak & show", "blue artifacts", "mono u belcher", "mono b helm", "mono u delver",
    "mono u faeries", "mono u terror", "mono-blue terror", "u post", "u terror", "u tron",
    "bogle", "welder-cam", "caw-gates", "g cloudpost", "eldrazis", "esper goryos",
    "golgari garden", "mono g landfall", "g post", "mono r madness", "mono-red madness",
    "r madness", "merfolks", "momo white", "mono r rally", "mono r stompy",
    "tron monsters", "tron monster", "ninjas", "omni show", "rally red", "walls spy",
    "w stax", "urza tron", "weenie white",
)


def plan(con) -> list[tuple[str, str, int]]:
    keys = {k: ALIASES[k] for k in KEYS_2026_09_28}
    out = []
    for label, n in con.execute(
            "SELECT archetype, COUNT(*) FROM decks WHERE archetype IS NOT NULL GROUP BY archetype"):
        target = keys.get(label.lower())
        if target and target != label:
            out.append((label, target, n))
    return sorted(out, key=lambda x: -x[2])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--db", type=Path)
    a = ap.parse_args(argv)
    from db.database import DB_PATH
    db = Path(a.db or DB_PATH)
    ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    changes = plan(ro)
    print(f"{len(changes)} labels, {sum(n for *_, n in changes)} decks:")
    for label, target, n in changes:
        print(f"  {n:5d}  {label!r} -> {target!r}")
    if not a.commit:
        print("DRY-RUN: nothing written.")
        return 0
    bak = db.with_name(f"{db.stem}.backup-{datetime.now():%Y-%m-%d-%H%M}-pre-aliases.db")
    dst = sqlite3.connect(bak)
    ro.backup(dst)
    assert dst.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    dst.close()
    ro.close()
    print(f"backup: {bak}")
    con = sqlite3.connect(db, timeout=60)
    try:
        with con:
            for label, target, _n in changes:
                con.execute("UPDATE decks SET archetype = ? WHERE archetype = ?", (target, label))
    finally:
        con.close()
    print(f"COMMITTED: {len(changes)} labels renamed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
