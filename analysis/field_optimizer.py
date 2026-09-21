"""
Field Optimizer — calculate weighted win rates against a specific expected field.

Split from win_rates.py for maintainability.
"""

import re
from db.database import get_combined_connection
from analysis.win_rates import _fetch_appearances, _best_per_event, _matchup_stats, _confidence_label


def parse_field_string(field_str):
    """
    Parse a field specification string into {archetype_name: count}.

    Supported formats (comma-separated entries):
      "Izzet Prowess x4"
      "Izzet Prowess x 4"
      "Izzet Prowess 4"
      "4 Izzet Prowess"
      "Izzet Prowess"        (count defaults to 1)

    Returns dict mapping archetype name -> integer count.
    """
    field = {}
    for entry in field_str.split(','):
        entry = entry.strip()
        if not entry:
            continue

        # "Name x4" or "Name x 4"
        m = re.match(r'^(.+?)\s+x\s*(\d+)$', entry, re.IGNORECASE)
        if m:
            field[m.group(1).strip()] = int(m.group(2))
            continue

        # "4 Name"
        m = re.match(r'^(\d+)\s+(.+)$', entry)
        if m:
            field[m.group(2).strip()] = int(m.group(1))
            continue

        # "Name 4"
        m = re.match(r'^(.+?)\s+(\d+)$', entry)
        if m:
            field[m.group(1).strip()] = int(m.group(2))
            continue

        # Just "Name" (count = 1)
        field[entry] = 1

    return field


def optimize_field_composition(field, format_name="standard",
                                include_archive=False, since=None, until=None):
    """
    Calculate weighted win rates for each archetype against a specific expected field.

    field: dict of {archetype_name: count}, e.g. {"Izzet Prowess": 4, "Mono Green": 3}
    Each entry should use a partial archetype name that matches the DB via LIKE.

    Returns:
    {
        "field": {archetype: count},
        "total_players": int,
        "results": [
            {
                "archetype":           str,
                "field_count":         int,
                "weighted_win_rate":   float,   # 0.0-1.0 weighted against the field
                "confidence":          str,     # overall: high/medium/low/none
                "matchups": [
                    {
                        "opponent":        str,
                        "opponent_count":  int,
                        "weight":          float,  # fraction of opponent slots in field
                        "win_rate":        float,
                        "shared_events":   int,
                        "confidence":      str,
                        "favored":         bool,   # win_rate > 0.5
                    },
                    ...
                ],
            },
            ...  (sorted by weighted_win_rate descending)
        ],
        "best_deck":  str,   # highest weighted win rate
        "note": str,
    }
    """
    archetypes = list(field.keys())
    total_players = sum(field.values())

    conn = get_combined_connection(include_archive=include_archive)
    try:
        # Fetch best-per-event for every archetype in the field
        all_best = {}
        for arch in archetypes:
            rows = _fetch_appearances(conn, arch, format_name, since=since, until=until)
            all_best[arch] = _best_per_event(rows)
    finally:
        conn.close()

    results = []
    for arch in archetypes:
        arch_count    = field[arch]
        # Opponents = everyone else in the field
        opp_total     = total_players - arch_count
        if opp_total <= 0:
            # Only archetype in the field
            results.append({
                "archetype":         arch,
                "field_count":       arch_count,
                "weighted_win_rate": None,
                "confidence":        "none",
                "matchups":          [],
            })
            continue

        matchup_details = []
        weighted_sum    = 0.0
        min_shared      = None

        for opp in archetypes:
            if opp == arch:
                continue
            opp_count = field[opp]
            weight    = opp_count / opp_total

            stats = _matchup_stats(all_best[arch], all_best[opp])
            if stats is None:
                wr             = 0.5   # no data: assume even
                shared_events  = 0
                confidence     = "none"
            else:
                wr             = stats["win_rate"]
                shared_events  = stats["shared_events"]
                confidence     = _confidence_label(shared_events)

            weighted_sum += wr * weight

            if min_shared is None or shared_events < min_shared:
                min_shared = shared_events

            matchup_details.append({
                "opponent":       opp,
                "opponent_count": opp_count,
                "weight":         round(weight, 3),
                "win_rate":       wr,
                "shared_events":  shared_events,
                "confidence":     confidence,
                "favored":        wr > 0.5,
            })

        # Sort matchups: most impactful (weight * abs deviation from 0.5) first
        matchup_details.sort(
            key=lambda m: m["weight"] * abs(m["win_rate"] - 0.5),
            reverse=True
        )

        overall_confidence = _confidence_label(min_shared if min_shared is not None else 0)

        results.append({
            "archetype":         arch,
            "field_count":       arch_count,
            "weighted_win_rate": round(weighted_sum, 3),
            "confidence":        overall_confidence,
            "matchups":          matchup_details,
        })

    results.sort(
        key=lambda r: r["weighted_win_rate"] if r["weighted_win_rate"] is not None else -1,
        reverse=True
    )

    best_deck = results[0]["archetype"] if results else None

    return {
        "field":          field,
        "total_players":  total_players,
        "format":         format_name,
        "results":        results,
        "best_deck":      best_deck,
        "note": (
            "Win rates are based on placement comparison in shared events, not actual match records. "
            "Matchups with no data default to 50%."
        ),
    }
