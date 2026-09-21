"""Data-health + Chapin conversion-ratio report (read-only diagnostic).

Two things the dashboard does not currently tell you:

1. FRESHNESS -- per-format, the last date we actually have match rows for, and
   the monthly volume trend.  `data/scrape_state.json` reports overall status
   only, so a format-specific scrape stall is invisible.

2. CONVERSION RATIO -- Chapin's Information Cascades test (Next Level Magic
   Forever, p.92).  An archetype's share of top finishes divided by its share
   of the field.  A deck sitting near 1.00 with a middling win rate is winning
   because it is everywhere, not because it is good.  `meta_scoring.py` only
   flags a deck as a Trap when its win rate is below 48%, so cascade decks
   with a ~50% win rate are currently labelled Fringe or nothing.

Both field and top-cut are derived from the SAME source (the `matches` table),
because `decks` is top-cut biased -- ~12 rows per event, placement values
bucketed at 4/8/16/32 -- and its archetype labels come from a different
scraper than the melee match rows.  Mixing them produces nonsense (archetypes
with 5% of the field and 0.0% of top 8s).

Usage:
    python scripts/data_health_report.py
    python scripts/data_health_report.py --format modern --since 2025-10-01
    python scripts/data_health_report.py --freshness-only
"""
from __future__ import annotations

import argparse
import collections
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import DB_PATH  # noqa: E402

FORMATS = ("modern", "standard", "legacy", "pauper", "pioneer")


def norm_month(d: str | None) -> str | None:
    """`matches.event_date` and `events.date` hold BOTH 'YYYY-MM-DD' and
    'dd/mm/yy'.  Plain string comparison across the two is meaningless."""
    if not d:
        return None
    d = d.strip()
    if len(d) >= 10 and d[4] == "-":
        return d[:7]
    if "/" in d:
        parts = d.split("/")
        if len(parts) == 3:
            _, mm, yy = parts
            return f"{yy if len(yy) == 4 else '20' + yy}-{mm.zfill(2)}"
    return None


def freshness(con, months: int = 12) -> None:
    counts: collections.Counter = collections.Counter()
    for fmt, date in con.execute("SELECT lower(format), event_date FROM matches"):
        m = norm_month(date)
        if m:
            counts[(fmt, m)] += 1

    print("=== match rows per month, by format ===")
    print("month     " + "".join(f"{f[:9]:>10}" for f in FORMATS))
    for m in sorted({mm for _, mm in counts}, reverse=True)[:months]:
        print(f"{m:<9} " + "".join(f"{counts.get((f, m), 0):>10}" for f in FORMATS))

    print("\n=== last month with any match data ===")
    for f in FORMATS:
        ms = sorted([m for (ff, m) in counts if ff == f], reverse=True)
        print(f"  {f:<10} {ms[0] if ms else 'NONE'}")

    iso = con.execute(
        "SELECT COUNT(*) FROM matches WHERE event_date LIKE '____-__-__'").fetchone()[0]
    slash = con.execute(
        "SELECT COUNT(*) FROM matches WHERE instr(event_date,'/')>0").fetchone()[0]
    print(f"\n  matches.event_date  iso={iso}  dd/mm/yy={slash}"
          "   <- mixed formats in one column; never compare as strings")

    state = Path(__file__).resolve().parent.parent / "data" / "scrape_state.json"
    if state.exists():
        import json
        st = json.loads(state.read_text(encoding="utf-8"))
        print(f"  scrape_state.json: last_updated={st.get('last_updated')} "
              f"last_status={st.get('last_status')}")


def conversion(con, fmt: str, lo: str, hi: str,
               min_players: int = 16, cut: int = 8) -> None:
    """Field share, top-cut share and conversion, all from `matches`.

    The algorithm lives in analysis.conversion.conversion_by_archetype (ported
    from here on 2026-09-21 and verified digit-for-digit); this function is
    the CLI presentation of it.
    """
    from analysis.conversion import conversion_by_archetype
    from analysis.meta_scoring import classify_status

    out = conversion_by_archetype(fmt, lo, hi, min_players=min_players,
                                  cut=cut, con=con)
    if not out:
        print(f"\nNo {fmt} match data in {lo}..{hi} -- nothing to score.")
        return

    n_events = next(iter(out.values()))["events_total"]
    print(f"\n=== {fmt} conversion, {lo}..{hi} "
          f"({n_events} events with >={min_players} players) ===")
    print(f"{'archetype':<26}{'field%':>8}{'top%':>8}{'conv':>8}"
          f"{'matchWR':>9}{'n':>8}")
    print("-" * 68)
    flagged = []
    ranked = sorted(out.items(), key=lambda kv: -kv[1]["field_share"])[:20]
    for arch, r in ranked:
        fs, ts, conv, wr, n = (r["field_share"], r["top_share"], r["conversion"],
                               r["match_wr"], r["matches"])
        print(f"{arch[:26]:<26}{fs*100:>7.2f}%{ts*100:>7.2f}%{conv:>8.2f}"
              f"{wr*100:>8.1f}%{n:>8}")
        if classify_status(fs, wr, conversion=conv)[0] == "Cascade":
            flagged.append((arch, fs, conv, wr, n))

    print("\n--- cascade candidates (share >=3%, conv <=1.02, WR 48-52%) ---")
    for arch, fs, conv, wr, n in flagged or []:
        print(f"   {arch[:26]:<26} field={fs*100:5.2f}%  conv={conv:.2f}  "
              f"WR={wr*100:.1f}%  n={n}")
    if not flagged:
        print("   (none)")
    print("\n  Caveat: top cut is approximated by swiss win count from match rows.")
    print("  No tiebreakers, drops or byes, and the cut is a flat top-%d regardless"
          % cut)
    print("  of event size. Treat conversion as a signal, not a standing.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="modern")
    ap.add_argument("--since", default="2025-10-01")
    ap.add_argument("--until", default="2099-01-01")
    ap.add_argument("--min-players", type=int, default=16)
    ap.add_argument("--cut", type=int, default=8)
    ap.add_argument("--freshness-only", action="store_true")
    args = ap.parse_args()

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    con = sqlite3.connect(str(DB_PATH))
    print(f"DB: {DB_PATH}\n")
    freshness(con)
    if not args.freshness_only:
        conversion(con, args.format.lower(), args.since, args.until,
                   args.min_players, args.cut)


if __name__ == "__main__":
    main()
