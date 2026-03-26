"""
scripts/analyze_duplicates.py

Read-only duplicate inspection for events and decks.

Calls core/data_engine/duplicate_analysis.py — no writes, no merges.

Usage:
    python scripts/analyze_duplicates.py                    # full summary
    python scripts/analyze_duplicates.py --events           # event dups only
    python scripts/analyze_duplicates.py --decks            # deck dups only
    python scripts/analyze_duplicates.py --cross-source     # cross-source deck dups only
    python scripts/analyze_duplicates.py --format standard  # filter by format
    python scripts/analyze_duplicates.py --top 20           # show top N clusters
    python scripts/analyze_duplicates.py --include-archive  # query both DBs
    python scripts/analyze_duplicates.py --summary-only     # stats, no clusters
"""

import sys
import os
import argparse
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.data_engine.duplicate_analysis import (
    get_duplicate_events,
    get_duplicate_decks,
    get_duplicate_summary,
)
from db.database import get_connection, get_combined_connection


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _banner(text):
    print()
    print("=" * 64)
    print(f"  {text}")
    print("=" * 64)


def _section(text):
    print()
    print(f"--- {text} ---")


def _pct(n, total):
    return f"{n * 100 / total:.1f}%" if total else "0.0%"


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(summary):
    ev = summary["events"]
    dk = summary["decks"]
    fh = summary["fingerprint_health"]

    _banner("Duplicate Summary")

    # Events
    _section("Events")
    print(f"  Total events          : {ev['total']:>7,}")
    print(f"  In duplicate groups   : {ev['in_dup_groups']:>7,}  ({_pct(ev['in_dup_groups'], ev['total'])})")
    print(f"  Duplicate groups      : {ev['dup_groups']:>7,}")
    print()
    print("  By type:")
    for t, cnt in ev["by_type"].items():
        print(f"    {t:<30} {cnt:>5,}")
    print()
    print("  By source:")
    for src, d in sorted(ev["by_source"].items()):
        print(f"    {src:<20} total={d['total']:>6,}  in_dups={d['in_dups']:>6,}  ({_pct(d['in_dups'], d['total'])})")

    # Decks
    _section("Decks")
    print(f"  Total decks           : {dk['total']:>7,}")
    print(f"  In duplicate groups   : {dk['in_dup_groups']:>7,}  ({_pct(dk['in_dup_groups'], dk['total'])})")
    print(f"  Duplicate groups      : {dk['dup_groups']:>7,}")
    print(f"  Cross-source groups   : {dk['cross_source_groups']:>7,}")
    print(f"  Cross-source decks    : {dk['cross_source_decks']:>7,}")
    print()
    print("  By type:")
    for t, cnt in dk["by_type"].items():
        print(f"    {t:<30} {cnt:>5,}")
    print()
    print("  By format:")
    for fmt, d in sorted(dk["by_format"].items()):
        if not fmt:
            continue
        print(f"    {fmt:<20} total={d['total']:>6,}  in_dups={d['in_dups']:>6,}  ({_pct(d['in_dups'], d['total'])})")
    print()
    print("  By source:")
    for src, d in sorted(dk["by_source"].items()):
        print(f"    {src:<20} total={d['total']:>6,}  in_dups={d['in_dups']:>6,}  ({_pct(d['in_dups'], d['total'])})")

    # Fingerprint health
    _section("Fingerprint Health")
    rate = fh["event_false_positive_rate"]
    print(f"  Event false-positive rate : {rate:.1%}")
    print(f"  Note: {fh['note']}")


# ---------------------------------------------------------------------------
# Event cluster printer
# ---------------------------------------------------------------------------

def print_event_clusters(groups, top_n, fmt_filter):
    if fmt_filter:
        groups = [g for g in groups if fmt_filter in [f.lower() for f in g["formats"]]]

    shown = groups[:top_n]

    _banner(f"Event Duplicate Clusters  (showing top {len(shown)} of {len(groups)})")

    if not shown:
        print("  No event duplicates found.")
        return

    for i, g in enumerate(shown, 1):
        dup_type = g["duplicate_type"]
        marker = " [CROSS-SOURCE]" if dup_type == "cross_source" else ""
        print(f"\n  #{i}  fp={g['fingerprint']}  count={g['count']}  type={dup_type}{marker}")
        print(f"       formats : {', '.join(g['formats']) or '(unknown)'}")
        print(f"       dates   : {', '.join(g['dates'])}")
        print(f"       sources : {dict(g['source_counts'])}")
        # Sample members (up to 4)
        for m in g["members"][:4]:
            print(f"         id={m['id']:<6} [{m['source']:<12}] {m['name'] or '(no name)':<50}  {m['date'] or ''}")
        if g["count"] > 4:
            print(f"         ... and {g['count'] - 4} more")


# ---------------------------------------------------------------------------
# Deck cluster printer
# ---------------------------------------------------------------------------

def print_deck_clusters(groups, top_n, fmt_filter, cross_source_only):
    if fmt_filter:
        groups = [g for g in groups if fmt_filter in [f.lower() for f in g["formats"]]]
    if cross_source_only:
        groups = [g for g in groups if g["duplicate_type"] == "cross_source"]

    shown = groups[:top_n]

    label = "Cross-Source " if cross_source_only else ""
    _banner(f"{label}Deck Duplicate Clusters  (showing top {len(shown)} of {len(groups)})")

    if not shown:
        print("  No deck duplicates found.")
        return

    for i, g in enumerate(shown, 1):
        dup_type = g["duplicate_type"]
        marker = " [CROSS-SOURCE]" if dup_type == "cross_source" else ""
        print(f"\n  #{i}  fp={g['fingerprint']}  count={g['count']}  type={dup_type}{marker}")
        print(f"       formats   : {', '.join(g['formats']) or '(unknown)'}")
        print(f"       archetypes: {', '.join(g['archetypes']) or '(unknown)'}")
        print(f"       sources   : {dict(g['source_counts'])}")
        players = g["players"]
        if players:
            sample = ", ".join(players[:3])
            suffix = f" (+{len(players) - 3} more)" if len(players) > 3 else ""
            print(f"       players   : {sample}{suffix}")
        # Sample members (up to 4)
        for m in g["members"][:4]:
            print(
                f"         deck={m['deck_id']:<6} [{m['event_source']:<12}] "
                f"{(m['player'] or 'unknown'):<20}  {m['event_name'] or '(no event)':<45}  {m['event_date'] or ''}"
            )
        if g["count"] > 4:
            print(f"         ... and {g['count'] - 4} more")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Inspect event and deck duplicates (read-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--events",          action="store_true", help="Show event duplicate clusters")
    parser.add_argument("--decks",           action="store_true", help="Show deck duplicate clusters")
    parser.add_argument("--cross-source",    action="store_true", help="Show only cross-source deck clusters")
    parser.add_argument("--summary-only",    action="store_true", help="Show summary stats only, no clusters")
    parser.add_argument("--format",          metavar="FMT",       help="Filter clusters by format (e.g. standard)")
    parser.add_argument("--top",             type=int, default=10, metavar="N", help="Show top N clusters (default: 10)")
    parser.add_argument("--include-archive", action="store_true", help="Include archive DB in analysis")
    args = parser.parse_args()

    # Default: show both if neither flag set
    show_events = args.events or (not args.events and not args.decks and not args.cross_source)
    show_decks  = args.decks  or args.cross_source or (not args.events and not args.decks)

    fmt_filter = (args.format or "").lower().strip() or None

    if args.include_archive:
        conn = get_combined_connection(include_archive=True)
    else:
        conn = get_connection()

    try:
        summary = get_duplicate_summary(conn)
        print_summary(summary)

        if args.summary_only:
            print()
            return

        if show_events:
            groups = get_duplicate_events(conn)
            print_event_clusters(groups, args.top, fmt_filter)

        if show_decks:
            groups = get_duplicate_decks(conn)
            print_deck_clusters(groups, args.top, fmt_filter, args.cross_source)

    finally:
        conn.close()

    print()


if __name__ == "__main__":
    main()
