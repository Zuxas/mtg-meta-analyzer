"""
Conversion ratio -- Chapin's Information Cascades test (NLMF p.92, rule IC-02).

A deck that is played a lot wins a lot in absolute terms, which fuels more
play. The test that separates "good" from "popular" is

    conversion = (share of top finishes) / (share of field)

Near 1.00 means the deck's presence in the top cut is explained by how much it
is played. Well above 1 it over-performs its numbers; well below, it is a
cascade candidate: everywhere, and not winning.

Field AND top cut are derived from the `matches` table ONLY. Do not join to
`decks`: it is top-cut biased (~12 rows per event, placements bucketed at
4/8/16/32) so it cannot supply a field denominator, and its archetype labels
come from a different scraper than the melee match rows, so the label sets do
not reconcile (mixing them produced "Mono Red Aggro 5.3% of field, 0.03% of
top 8s" -- an artifact, not a finding).

Honest limits: the top cut is APPROXIMATED from win count over the event's
match rows, with no tiebreakers, drops or byes, and a flat top-`cut`
regardless of event size. Bracket rows (source `bracket_*`), where present,
count toward wins like any other row. It is a signal, not a standing.

Ported from scripts/data_health_report.py (the reference implementation);
differences: dates are normalized (db.helpers.SQL_NORM_DATE) so `dd/mm/yy`
rows are inside the window instead of silently dropped, and the result is a
dict for the dashboard / scoring layer rather than printed.
"""
import collections

from db.helpers import SQL_NORM_DATE

_NORM = SQL_NORM_DATE.format(col="event_date")


def conversion_by_archetype(format_name: str, since: str, until: str | None = None,
                            min_players: int = 16, cut: int = 8, *, con=None) -> dict:
    """
    {archetype: {field_share, top_share, conversion, match_wr,
                 matches, events, events_total, ci_low, ci_high}}

    `since` / `until` are ISO `YYYY-MM-DD` (until defaults to open-ended).
    Only events with >= `min_players` distinct players count. `matches` is
    the number of player-match results for the archetype (each match row
    contributes one result to each side). `events` is the number of
    qualifying events in which the archetype appeared; `events_total` is the
    number of qualifying events overall (same on every row). `ci_low`/`ci_high`
    is the Wilson 95% interval on `match_wr` (analysis.wilson.wilson_bounds).
    `con` is injectable for tests; default is the live DB.
    """
    from analysis.archetypes import normalize as norm_arch
    from analysis.win_rates import is_all_formats
    from analysis.wilson import wilson_bounds

    own = con is None
    if own:
        from db.database import get_connection
        con = get_connection()
    try:
        fmt_clause = "" if is_all_formats(format_name) else "AND lower(format) = ?"
        params = [since, until or "9999-12-31"]
        if fmt_clause:
            params.append(format_name.lower())
        rows = con.execute(f"""
            SELECT event_id, player1, player2, player1_arch, player2_arch, result
              FROM matches
             WHERE {_NORM} BETWEEN ? AND ?
               {fmt_clause}
        """, params).fetchall()
    finally:
        if own:
            con.close()

    # event -> player -> [wins, losses, archetype]
    events: dict = collections.defaultdict(dict)
    for eid, p1, p2, a1, a2, res in rows:
        for player, arch, won in ((p1, a1, res == "player1"),
                                  (p2, a2, res == "player2")):
            if not player:
                continue
            rec = events[eid].setdefault(player, [0, 0, None])
            if arch and rec[2] is None:
                rec[2] = norm_arch(arch)
            if res in ("player1", "player2"):
                rec[0 if won else 1] += 1

    field = collections.Counter()
    topcut = collections.Counter()
    wins = collections.Counter()
    played = collections.Counter()
    n_events = collections.Counter()
    qualifying = 0
    for players in events.values():
        if len(players) < min_players:
            continue
        qualifying += 1
        ranked = sorted(players.items(), key=lambda kv: (-kv[1][0], kv[1][1]))
        seen = set()
        for i, (_player, (w, l, arch)) in enumerate(ranked):
            if not arch:
                continue
            field[arch] += 1
            wins[arch] += w
            played[arch] += w + l
            if i < cut:
                topcut[arch] += 1
            if arch not in seen:
                seen.add(arch)
                n_events[arch] += 1

    total_field, total_cut = sum(field.values()), sum(topcut.values())
    if not total_field:
        return {}

    out = {}
    for arch, n in field.items():
        fs = n / total_field
        ts = topcut.get(arch, 0) / total_cut if total_cut else 0.0
        n_played = played.get(arch, 0)
        wr = wins[arch] / n_played if n_played else 0.0
        lo, hi = wilson_bounds(wins[arch], n_played)
        out[arch] = {
            "field_share": fs,
            "top_share": ts,
            "conversion": (ts / fs) if fs else 0.0,
            "match_wr": wr,
            "matches": n_played,
            "events": n_events[arch],
            "events_total": qualifying,
            "ci_low": lo,
            "ci_high": hi,
        }
    return out
