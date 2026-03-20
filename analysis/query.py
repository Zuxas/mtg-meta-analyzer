"""
Natural language-style query interface for the MTG Meta Analyzer.

Usage:
    python -m analysis.query average "Izzet Prowess"
    python -m analysis.query average "Izzet Prowess" --format standard
    python -m analysis.query compare --deck-id 42 --archetype "Izzet Prowess"
    python -m analysis.query top-cards --format standard --top 20
    python -m analysis.query last-challenge --format standard
    python -m analysis.query search "Prowess"
"""

import argparse
import sys
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from analysis.deck_analysis import (
    get_average_deck,
    compare_deck_to_average,
    get_deck_by_id,
    get_deck_by_placement,
    get_recent_event,
    search_decks,
)
from db.database import get_connection


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _pct(f):
    return f"{f*100:.0f}%"


def print_average_deck(avg, show_sideboard=True):
    print(f"\n=== Average {avg['archetype']} ({avg['format'].upper()}) ===")
    print(f"    Built from {avg['deck_count']} decklists\n")

    print("  MAINBOARD")
    for c in avg["mainboard"]:
        bar = "#" * c["suggested_qty"]
        print(f"    {c['suggested_qty']}x  {c['name']:<35} "
              f"[{_pct(c['inclusion_rate'])} of decks, "
              f"avg {c['avg_qty_in']:.1f} when played]")

    if show_sideboard and avg["sideboard"]:
        print("\n  SIDEBOARD")
        for c in avg["sideboard"]:
            print(f"    {c['suggested_qty']}x  {c['name']:<35} "
                  f"[{_pct(c['inclusion_rate'])} of decks]")
    print()


def print_comparison(comp, deck_info=None):
    if "error" in comp:
        print(f"\nERROR: {comp['error']}\n")
        return

    if deck_info:
        print(f"\n=== {deck_info.get('player','?')} - {deck_info.get('archetype','?')} ===")
        print(f"    Event : {deck_info.get('event_name','?')} ({deck_info.get('date','?')})")
        print(f"    Place : #{deck_info.get('placement','?')}")

    print(f"\n    Compared to average {comp['archetype']} "
          f"({comp['deck_count']} decks) | "
          f"Similarity: {comp['similarity_score']*100:.0f}%\n")

    for zone_name, zone in [("MAINBOARD", comp["mainboard"]),
                             ("SIDEBOARD", comp["sideboard"])]:
        has_diff = zone["added"] or zone["cut"] or zone["adjusted"]
        if not has_diff:
            continue
        print(f"  {zone_name}")

        if zone["added"]:
            print("    + ADDED (not in average):")
            for c in zone["added"]:
                print(f"        {c['qty']}x  {c['name']}")

        if zone["cut"]:
            print("    - CUT (in average, not here):")
            for c in zone["cut"]:
                print(f"        {c['avg_qty']}x  {c['name']:<35} ({c['note']})")

        if zone["adjusted"]:
            print("    ~ ADJUSTED quantity:")
            for c in zone["adjusted"]:
                arrow = "+" if c["diff"] > 0 else ""
                print(f"        {c['this_qty']}x vs avg {c['avg_qty']}x  "
                      f"{c['name']}  ({arrow}{c['diff']})")
        print()


def print_top_cards(format_name, top=20, include_archive=False):
    """Show the most-played cards across all decks in a format."""
    from db.database import get_combined_connection
    conn = get_combined_connection(include_archive=include_archive)
    try:
        rows = conn.execute("""
            SELECT c.name,
                   COUNT(DISTINCT dc.deck_id) as deck_count,
                   SUM(dc.quantity) as total_copies,
                   AVG(dc.quantity) as avg_copies,
                   dc.is_sideboard
            FROM deck_cards dc
            JOIN cards c ON c.id = dc.card_id
            JOIN decks d ON d.id = dc.deck_id
            JOIN events e ON e.id = d.event_id
            WHERE lower(e.format) = lower(?) AND dc.is_sideboard = 0
            GROUP BY c.name
            ORDER BY deck_count DESC
            LIMIT ?
        """, (format_name, top)).fetchall()

        total_decks = conn.execute(
            "SELECT COUNT(DISTINCT d.id) FROM decks d "
            "JOIN events e ON e.id = d.event_id WHERE lower(e.format)=lower(?)",
            (format_name,)
        ).fetchone()[0]
    finally:
        conn.close()

    print(f"\n=== Top {top} Mainboard Cards — {format_name.upper()} "
          f"({total_decks} total decks) ===\n")
    for i, r in enumerate(rows, 1):
        pct = r["deck_count"] / total_decks * 100 if total_decks else 0
        print(f"  {i:>2}. {r['name']:<35} "
              f"{r['deck_count']:>4} decks ({pct:4.1f}%)  "
              f"avg {r['avg_copies']:.1f} copies")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MTG Meta Analyzer — query tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # average
    p_avg = sub.add_parser("average", help="Show the average decklist for an archetype")
    p_avg.add_argument("archetype", help='e.g. "Izzet Prowess"')
    p_avg.add_argument("--format", default="standard")
    p_avg.add_argument("--min-inclusion", type=float, default=0.25,
                       help="Min fraction of decks a card must appear in (default 0.25)")
    p_avg.add_argument("--include-archive", action="store_true")
    p_avg.add_argument("--no-sideboard", action="store_true")

    # compare
    p_cmp = sub.add_parser("compare", help="Compare a deck to its archetype average")
    p_cmp.add_argument("--deck-id", type=int, help="Deck ID from the database")
    p_cmp.add_argument("--archetype", help="Archetype to compare against")
    p_cmp.add_argument("--format", default="standard")
    p_cmp.add_argument("--min-inclusion", type=float, default=0.25)
    p_cmp.add_argument("--include-archive", action="store_true")

    # last-challenge
    p_lc = sub.add_parser("last-challenge",
                           help="Show 2nd-place deck from last MTGO Challenge vs average")
    p_lc.add_argument("--format", default="standard")
    p_lc.add_argument("--placement", type=int, default=2)

    # top-cards
    p_tc = sub.add_parser("top-cards", help="Most-played mainboard cards in a format")
    p_tc.add_argument("--format", default="standard")
    p_tc.add_argument("--top", type=int, default=20)
    p_tc.add_argument("--include-archive", action="store_true")

    # search
    p_s = sub.add_parser("search", help="Search decks by archetype name")
    p_s.add_argument("archetype")
    p_s.add_argument("--format", default=None)
    p_s.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.cmd == "average":
        avg = get_average_deck(
            args.archetype, args.format,
            min_inclusion=args.min_inclusion,
            include_archive=args.include_archive,
        )
        if not avg:
            print(f"\nNo decks found for '{args.archetype}' in {args.format}.\n")
        else:
            print_average_deck(avg, show_sideboard=not args.no_sideboard)

    elif args.cmd == "compare":
        if not args.deck_id:
            print("\n--deck-id is required for compare. "
                  "Use 'search' to find deck IDs.\n")
            return
        deck = get_deck_by_id(args.deck_id, include_archive=args.include_archive)
        if not deck:
            print(f"\nNo deck found with id={args.deck_id}\n")
            return
        archetype = args.archetype or deck["archetype"]
        comp = compare_deck_to_average(
            deck, archetype, args.format,
            min_inclusion=args.min_inclusion,
            include_archive=args.include_archive,
        )
        print_comparison(comp, deck_info=deck)

    elif args.cmd == "last-challenge":
        event = get_recent_event(args.format, event_type="mtgo_challenge_32")
        if not event:
            event = get_recent_event(args.format, event_type="mtgo_challenge_64")
        if not event:
            print(f"\nNo MTGO Challenge events found for {args.format}. "
                  "Run the challenge scraper first.\n")
            return
        print(f"\nMost recent challenge: {event['name']} ({event['date']})")
        deck = get_deck_by_placement(event["id"], placement=args.placement)
        if not deck:
            print(f"  No deck found at placement #{args.placement}.\n")
            return
        comp = compare_deck_to_average(deck, deck["archetype"], args.format)
        print_comparison(comp, deck_info=deck)

    elif args.cmd == "top-cards":
        print_top_cards(args.format, args.top,
                        include_archive=args.include_archive)

    elif args.cmd == "search":
        rows = search_decks(args.archetype, args.format, args.limit)
        if not rows:
            print(f"\nNo decks found for '{args.archetype}'.\n")
            return
        print(f"\n=== Decks matching '{args.archetype}' ===\n")
        for r in rows:
            print(f"  id={r['id']:<5} [{r['date']}] #{r['placement']:<3} "
                  f"{r['archetype']:<28} {r['player']:<18} {r['event_name'][:35]}")
        print()


if __name__ == "__main__":
    main()
