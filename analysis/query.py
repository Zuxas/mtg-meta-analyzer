"""
Natural language-style query interface for the MTG Meta Analyzer.

Usage:
    python -m analysis.query average "Izzet Prowess"
    python -m analysis.query average "Izzet Prowess" --format standard
    python -m analysis.query compare --deck-id 42 --archetype "Izzet Prowess"
    python -m analysis.query top-cards --format standard --top 20
    python -m analysis.query last-challenge --format standard
    python -m analysis.query search "Prowess"

    python -m analysis.query meta --format standard
    python -m analysis.query meta --format standard --range "last 30 days"
    python -m analysis.query trend "Izzet Prowess" --weeks 8
    python -m analysis.query trend "Izzet Prowess" --range "feb2-mar9"
    python -m analysis.query h2h "Izzet Prowess" "Azorius Control"
    python -m analysis.query matchups "Izzet Prowess" --range "last 60 days"
    python -m analysis.query matrix --format standard --top 10
    python -m analysis.query field-optimizer --field "Izzet Prowess x4, Mono Green x3, Azorius Control x2"
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
from analysis.win_rates import (
    parse_date_range,
    get_archetype_stats,
    get_meta_standings,
    get_archetype_trend,
    get_head_to_head,
    get_archetype_matchups,
    get_matchup_matrix,
    optimize_field_composition,
    parse_field_string,
)
from db.database import get_connection


# ---------------------------------------------------------------------------
# Date range helper
# ---------------------------------------------------------------------------

def _resolve_dates(args):
    """
    Return (since, until) datetimes from CLI args.
    --range takes precedence; falls back to --since/--until individually.
    """
    if hasattr(args, 'range') and args.range:
        since, until = parse_date_range(args.range)
        if since is None:
            print(f"  Warning: could not parse date range '{args.range}' — ignoring filter.")
        return since, until

    since = until = None
    if hasattr(args, 'since') and args.since:
        since, _ = parse_date_range(args.since)
        if since is None:
            print(f"  Warning: could not parse --since '{args.since}'.")
    if hasattr(args, 'until') and args.until:
        _, until = parse_date_range(args.until)
        if until is None:
            print(f"  Warning: could not parse --until '{args.until}'.")
    return since, until


def _date_label(since, until):
    """Human-readable label for a date range, e.g. '2025-01-01 to 2025-03-20'."""
    if since and until:
        return f"{since.strftime('%Y-%m-%d')} to {until.strftime('%Y-%m-%d')}"
    if since:
        return f"since {since.strftime('%Y-%m-%d')}"
    if until:
        return f"until {until.strftime('%Y-%m-%d')}"
    return "all time"


# ---------------------------------------------------------------------------
# Formatters — deck analysis
# ---------------------------------------------------------------------------

def _pct(f):
    return f"{f*100:.0f}%"


def print_average_deck(avg, show_sideboard=True):
    print(f"\n=== Average {avg['archetype']} ({avg['format'].upper()}) ===")
    print(f"    Built from {avg['deck_count']} decklists\n")

    print("  MAINBOARD")
    for c in avg["mainboard"]:
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

    print(f"\n=== Top {top} Mainboard Cards -- {format_name.upper()} "
          f"({total_decks} total decks) ===\n")
    for i, r in enumerate(rows, 1):
        pct = r["deck_count"] / total_decks * 100 if total_decks else 0
        print(f"  {i:>2}. {r['name']:<35} "
              f"{r['deck_count']:>4} decks ({pct:4.1f}%)  "
              f"avg {r['avg_copies']:.1f} copies")
    print()


# ---------------------------------------------------------------------------
# Formatters — win rates
# ---------------------------------------------------------------------------

def print_meta_standings(results, format_name, date_label):
    print(f"\n=== Meta Standings: {format_name.upper()} | {date_label} ===\n")
    print(f"  {'#':<3} {'Archetype':<30} {'Apps':>5} {'Top8%':>6} {'AvgPts':>7} {'EstW%':>6}  Confidence")
    print(f"  {'-'*3} {'-'*30} {'-'*5} {'-'*6} {'-'*7} {'-'*6}  ----------")
    for i, s in enumerate(results, 1):
        print(f"  {i:<3} {s['archetype']:<30} "
              f"{s['appearances']:>5} "
              f"{s['top8_rate']*100:>5.0f}% "
              f"{s['avg_points']:>7.2f} "
              f"{s['est_match_winpct']*100:>5.0f}%")
    print()


def print_trend(weekly, archetype, date_label):
    print(f"\n=== Trend: {archetype} | {date_label} ===\n")
    print(f"  {'Week Start':<12} {'Apps':>5} {'MetaShr':>8} {'Top8%':>6} {'AvgPts':>7} {'EstW%':>6}")
    print(f"  {'-'*12} {'-'*5} {'-'*8} {'-'*6} {'-'*7} {'-'*6}")
    for w in weekly:
        top8   = f"{w['top8_rate']*100:.0f}%"   if w['top8_rate']  is not None else "  N/A"
        pts    = f"{w['avg_points']:.2f}"         if w['avg_points'] is not None else "  N/A"
        winpct = f"{w['est_winpct']*100:.0f}%"   if w['est_winpct'] is not None else "  N/A"
        meta   = f"{w['meta_share']*100:.1f}%"
        print(f"  {w['week_start']:<12} {w['appearances']:>5} {meta:>8} {top8:>6} {pts:>7} {winpct:>6}")
    print()


def print_h2h(result):
    if "note" in result and result.get("shared_events", 0) == 0:
        print(f"\n  {result['note']}\n")
        return

    a = result["archetype_a"]
    b = result["archetype_b"]
    print(f"\n=== Head-to-Head: {a} vs {b} ===\n")
    print(f"  Shared events : {result['shared_events']}")
    print(f"  {a:<30} {result['a_wins']:>3} wins  ({result['a_win_rate']*100:.0f}%)  avg place {result['a_avg_placement']}")
    print(f"  {b:<30} {result['b_wins']:>3} wins  ({result['b_win_rate']*100:.0f}%)  avg place {result['b_avg_placement']}")
    print(f"  Ties          : {result['ties']}")
    print(f"  Confidence    : {result['confidence']}")
    print(f"\n  Recent events:")
    for m in result["matchups"][:10]:
        print(f"    [{m['date']}]  {m.get(a+'_place','?'):>3} vs {m.get(b+'_place','?'):>3}  -- {m['result']}")
        print(f"      {m['event'][:60]}")
    print(f"\n  Note: {result['note']}\n")


def print_matchups(matchups, archetype, date_label):
    if not matchups:
        print(f"\n  No matchup data found for '{archetype}'.\n")
        return

    print(f"\n=== Matchups: {archetype} | {date_label} ===\n")
    print(f"  {'Opponent':<32} {'W%':>5}  {'W':>3} {'L':>3} {'T':>3}  {'Events':>6}  Conf")
    print(f"  {'-'*32} {'-'*5}  {'-'*3} {'-'*3} {'-'*3}  {'-'*6}  ----")
    for m in matchups:
        favor = "+" if m["win_rate"] > 0.5 else ("-" if m["win_rate"] < 0.5 else "=")
        print(f"  {m['opponent']:<32} {favor}{m['win_rate']*100:4.0f}%  "
              f"{m['wins']:>3} {m['losses']:>3} {m['ties']:>3}  "
              f"{m['shared_events']:>6}  {m['confidence']}")
    print()


def print_matrix(data):
    archetypes = data["archetypes"]
    matrix     = data["matrix"]
    if not archetypes:
        print("\n  No matrix data.\n")
        return

    # Shorten names for display
    short = {}
    for a in archetypes:
        parts = a.split()
        short[a] = " ".join(p[:4] for p in parts)[:12]

    col_w = 8
    header = f"  {'Archetype':<28}"
    for a in archetypes:
        header += f"  {short[a]:>{col_w}}"
    print(f"\n=== Matchup Matrix ===\n")
    print(header)
    print("  " + "-" * (28 + (col_w + 2) * len(archetypes)))

    for arch_a in archetypes:
        row = f"  {arch_a:<28}"
        for arch_b in archetypes:
            if arch_a == arch_b:
                row += f"  {'---':>{col_w}}"
            elif arch_b in matrix.get(arch_a, {}):
                wr = matrix[arch_a][arch_b]["win_rate"]
                row += f"  {wr*100:>{col_w-1}.0f}%"
            else:
                row += f"  {'n/a':>{col_w}}"
        print(row)

    print(f"\n  {data['note']}")
    print(f"  Confidence: high=8+ events, medium=3-7, low=1-2, n/a=no shared events\n")


def print_field_optimizer(result):
    field   = result["field"]
    total   = result["total_players"]
    fmt     = result["format"]
    results = result["results"]

    print(f"\n=== Field Optimizer: {fmt.upper()} ===")
    print(f"    Expected field ({total} players):")
    for arch, cnt in field.items():
        share = cnt / total * 100
        print(f"      {arch:<30} x{cnt}  ({share:.0f}%)")

    print(f"\n  Ranked by weighted win rate against this field:\n")
    print(f"  {'#':<3} {'Archetype':<30} {'W%vsField':>10}  {'Count':>5}  Confidence")
    print(f"  {'-'*3} {'-'*30} {'-'*10}  {'-'*5}  ----------")

    for i, r in enumerate(results, 1):
        wwr = r["weighted_win_rate"]
        wwr_str = f"{wwr*100:.1f}%" if wwr is not None else "N/A"
        favor = ""
        if wwr is not None:
            favor = " [BEST]" if i == 1 else (" FAV" if wwr > 0.52 else (" UNF" if wwr < 0.48 else ""))
        print(f"  {i:<3} {r['archetype']:<30} {wwr_str:>10}  {r['field_count']:>5}  {r['confidence']}{favor}")

    best = result["best_deck"]
    if best:
        print(f"\n  Most favored: {best}")

    # Per-deck matchup breakdown
    print(f"\n  --- Matchup Breakdown ---")
    for r in results:
        if not r["matchups"]:
            continue
        wwr_str = f"{r['weighted_win_rate']*100:.1f}%" if r["weighted_win_rate"] is not None else "N/A"
        print(f"\n  {r['archetype']} (field win rate: {wwr_str})")
        for m in r["matchups"]:
            arrow = "+" if m["favored"] else "-"
            share = m["weight"] * 100
            wr    = m["win_rate"] * 100
            note  = "(no data)" if m["shared_events"] == 0 else f"{m['shared_events']} events [{m['confidence']}]"
            print(f"    {arrow} vs {m['opponent']:<28}  {wr:5.0f}%  weight:{share:.0f}%  {note}")

    print(f"\n  Note: {result['note']}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_date_args(parser):
    parser.add_argument("--range",
                        help="Date range: 'last 30 days', 'feb2-mar9', 'oct 25 2025 - today'")
    parser.add_argument("--since", help="Start date: 'feb 2' or '2025-02-02'")
    parser.add_argument("--until", help="End date: 'today' or '2025-03-20'")


def main():
    parser = argparse.ArgumentParser(description="MTG Meta Analyzer -- query tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # average
    p_avg = sub.add_parser("average", help="Show the average decklist for an archetype")
    p_avg.add_argument("archetype", help='e.g. "Izzet Prowess"')
    p_avg.add_argument("--format", default="standard")
    p_avg.add_argument("--min-inclusion", type=float, default=0.25)
    p_avg.add_argument("--include-archive", action="store_true")
    p_avg.add_argument("--no-sideboard", action="store_true")

    # compare
    p_cmp = sub.add_parser("compare", help="Compare a deck to its archetype average")
    p_cmp.add_argument("--deck-id", type=int)
    p_cmp.add_argument("--archetype")
    p_cmp.add_argument("--format", default="standard")
    p_cmp.add_argument("--min-inclusion", type=float, default=0.25)
    p_cmp.add_argument("--include-archive", action="store_true")

    # last-challenge
    p_lc = sub.add_parser("last-challenge",
                           help="Show Nth place deck from last MTGO Challenge vs average")
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

    # meta
    p_meta = sub.add_parser("meta", help="Meta standings: all archetypes ranked")
    p_meta.add_argument("--format", default="standard")
    p_meta.add_argument("--top", type=int, default=20)
    p_meta.add_argument("--min-appearances", type=int, default=3)
    p_meta.add_argument("--event-type", default=None)
    p_meta.add_argument("--include-archive", action="store_true")
    _add_date_args(p_meta)

    # trend
    p_trend = sub.add_parser("trend", help="Week-by-week trend for an archetype")
    p_trend.add_argument("archetype")
    p_trend.add_argument("--format", default="standard")
    p_trend.add_argument("--weeks", type=int, default=8)
    p_trend.add_argument("--event-type", default=None)
    p_trend.add_argument("--include-archive", action="store_true")
    _add_date_args(p_trend)

    # h2h
    p_h2h = sub.add_parser("h2h", help="Head-to-head between two archetypes")
    p_h2h.add_argument("archetype_a")
    p_h2h.add_argument("archetype_b")
    p_h2h.add_argument("--format", default="standard")
    p_h2h.add_argument("--include-archive", action="store_true")
    _add_date_args(p_h2h)

    # matchups
    p_mu = sub.add_parser("matchups", help="All matchup data for one archetype")
    p_mu.add_argument("archetype")
    p_mu.add_argument("--format", default="standard")
    p_mu.add_argument("--min-shared", type=int, default=2)
    p_mu.add_argument("--include-archive", action="store_true")
    _add_date_args(p_mu)

    # matrix
    p_mx = sub.add_parser("matrix", help="Full NxN matchup matrix for top archetypes")
    p_mx.add_argument("--format", default="standard")
    p_mx.add_argument("--top", type=int, default=12)
    p_mx.add_argument("--min-appearances", type=int, default=5)
    p_mx.add_argument("--include-archive", action="store_true")
    _add_date_args(p_mx)

    # field-optimizer
    p_fo = sub.add_parser("field-optimizer",
                           help="Rank decks by weighted win rate against an expected field")
    p_fo.add_argument("--field", required=True,
                      help='e.g. "Izzet Prowess x4, Mono Green x3, Azorius Control x2"')
    p_fo.add_argument("--format", default="standard")
    p_fo.add_argument("--include-archive", action="store_true")
    _add_date_args(p_fo)

    args = parser.parse_args()

    # -----------------------------------------------------------------------

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
            print("\n--deck-id is required for compare. Use 'search' to find deck IDs.\n")
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
        print_top_cards(args.format, args.top, include_archive=args.include_archive)

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

    elif args.cmd == "meta":
        since, until = _resolve_dates(args)
        results = get_meta_standings(
            format_name=args.format,
            event_type=args.event_type,
            min_appearances=args.min_appearances,
            top=args.top,
            include_archive=args.include_archive,
            since=since,
            until=until,
        )
        if not results:
            print(f"\nNo data found for {args.format}.\n")
        else:
            print_meta_standings(results, args.format, _date_label(since, until))

    elif args.cmd == "trend":
        since, until = _resolve_dates(args)
        weekly = get_archetype_trend(
            args.archetype,
            format_name=args.format,
            weeks=args.weeks,
            event_type=args.event_type,
            include_archive=args.include_archive,
            since=since,
            until=until,
        )
        if not weekly:
            print(f"\nNo trend data found for '{args.archetype}'.\n")
        else:
            print_trend(weekly, args.archetype, _date_label(since, until))

    elif args.cmd == "h2h":
        since, until = _resolve_dates(args)
        result = get_head_to_head(
            args.archetype_a,
            args.archetype_b,
            format_name=args.format,
            include_archive=args.include_archive,
            since=since,
            until=until,
        )
        print_h2h(result)

    elif args.cmd == "matchups":
        since, until = _resolve_dates(args)
        matchups = get_archetype_matchups(
            args.archetype,
            format_name=args.format,
            include_archive=args.include_archive,
            since=since,
            until=until,
            min_shared_events=args.min_shared,
        )
        print_matchups(matchups, args.archetype, _date_label(since, until))

    elif args.cmd == "matrix":
        since, until = _resolve_dates(args)
        data = get_matchup_matrix(
            format_name=args.format,
            min_appearances=args.min_appearances,
            include_archive=args.include_archive,
            since=since,
            until=until,
            top=args.top,
        )
        print_matrix(data)

    elif args.cmd == "field-optimizer":
        since, until = _resolve_dates(args)
        field = parse_field_string(args.field)
        if not field:
            print("\nCould not parse --field. Example: 'Izzet Prowess x4, Mono Green x3'\n")
            return
        result = optimize_field_composition(
            field,
            format_name=args.format,
            include_archive=args.include_archive,
            since=since,
            until=until,
        )
        print_field_optimizer(result)


if __name__ == "__main__":
    main()
