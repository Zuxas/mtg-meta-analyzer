"""
Field Optimizer — calculate weighted win rates against a specific expected field.

Split from win_rates.py for maintainability.
"""

import re
from db.database import get_combined_connection, DB_PATH as CENTRAL_DB_PATH
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


def _legacy_unused_compute_deck_ev_moved_to_deck_ev_module(
    deck_id: int,
    field_shares: dict = None,
    format_name: str = "standard",
    pre_post_bumps: dict = None,
) -> dict:
    """Compute expected field-weighted win rate for a saved deck.

    Combines three data sources per matchup, in priority order:
      1. Paper real-match WR (mtg_meta.db matches, via win_rates.get_real_matchup_winrates)
      2. Untapped Bo3 matchup matrix (premium endpoint)
      3. Fall back to 0.5 (no data)

    Applies SB difficulty bumps from saved_sb_plans:
      Easy   = +5% to pre-board WR (you adjust well)
      Medium = +0% (treads water)
      Hard   = -5% (SB doesn't flip it)

    Args:
      deck_id: saved_decks.id row to evaluate.
      field_shares: {archetype_name: fraction}. None = derive from last 14d
                    MTGO/paper meta in mtg_meta.db.
      format_name: 'standard' (default).
      pre_post_bumps: override default per-difficulty deltas (mapping
                      difficulty -> WR delta as float, e.g. {"Easy": 0.05}).

    Returns:
      {
        "deck_name": str,
        "deck_archetype": str,
        "field_total_share": float,            # should sum to ~1.0
        "field_weighted_wr": float,            # the headline number
        "rows": [
          {"opponent": str, "share": float,
           "pre_board_wr": float, "post_board_wr": float,
           "difficulty": str, "source": str,   # 'paper' | 'untapped' | 'guess'
           "sample_n": int, "contribution": float},
          ...
        ],
        "best": [...top 5 favorable matchup contributions],
        "worst": [...bottom 5 unfavorable matchup contributions],
        "low_confidence_share": float,         # fraction of field with n<20
      }
    """
    from db.saved_decks import get_deck, get_sb_plans
    from analysis.archetypes import normalize as norm_arch
    from analysis.win_rates import get_real_matchup_winrates
    from db.untapped_queries import get_untapped_matchup_matrix
    from datetime import datetime, timedelta
    import sqlite3
    from pathlib import Path

    deck = get_deck(deck_id)
    if not deck:
        return {"error": f"deck_id {deck_id} not found"}

    deck_archetype = norm_arch(deck.get("archetype", ""))

    # Build field_shares from 14d meta if not provided
    if field_shares is None:
        field_shares = {}
        with sqlite3.connect(str(CENTRAL_DB_PATH)) as con:
            since = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
            total = con.execute(f"""
                SELECT COUNT(*) FROM decks d JOIN events e ON e.id=d.event_id
                WHERE lower(e.format) = ?
                  AND (CASE WHEN instr(e.date,'/')>0
                    THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2)
                    ELSE replace(e.date,'-','') END) >= '{since}'
            """, (format_name.lower(),)).fetchone()[0]
            if total <= 0:
                return {"error": "no recent meta data"}
            rows = con.execute(f"""
                SELECT d.archetype, COUNT(*) as n
                FROM decks d JOIN events e ON e.id=d.event_id
                WHERE lower(e.format) = ?
                  AND (CASE WHEN instr(e.date,'/')>0
                    THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2)
                    ELSE replace(e.date,'-','') END) >= '{since}'
                GROUP BY d.archetype HAVING n >= ?
                ORDER BY n DESC
            """, (format_name.lower(), max(3, total // 100))).fetchall()
            for arch, n in rows:
                field_shares[norm_arch(arch)] = n / total

    # Normalize keys + drop self
    norm_shares = {}
    for k, v in field_shares.items():
        nk = norm_arch(k)
        if nk == deck_archetype:
            # Mirror -- include but as a single bucket; assume 50% WR
            norm_shares[nk] = norm_shares.get(nk, 0.0) + v
        else:
            norm_shares[nk] = norm_shares.get(nk, 0.0) + v

    # Pull matchup data
    real_raw = get_real_matchup_winrates(format_name, min_matches=10)
    real_for_us = {}
    real_n_for_us = {}
    for a, opps in real_raw.items():
        na = norm_arch(a)
        for b, stats in opps.items():
            nb = norm_arch(b)
            if na == deck_archetype:
                real_for_us[nb] = stats["win_rate"]
                real_n_for_us[nb] = stats["total"]
            elif nb == deck_archetype:
                real_for_us[na] = 1.0 - stats["win_rate"]
                real_n_for_us[na] = stats["total"]

    untapped = get_untapped_matchup_matrix(format_name)
    untapped_for_us = {}
    untapped_n_for_us = {}
    for opp, stats in (untapped.get(deck_archetype, {}) or {}).items():
        untapped_for_us[opp] = stats["winrate"]
        untapped_n_for_us[opp] = stats["matches"]

    # SB difficulty -> delta (default)
    bumps = pre_post_bumps or {"Easy": 0.05, "Medium": 0.0, "Hard": -0.05}
    sb_plans = get_sb_plans(deck_id)
    diff_by_opp = {}
    for p in sb_plans:
        diff_by_opp[norm_arch(p.get("opponent_archetype", ""))] = p.get("difficulty", "Medium")

    # Build rows
    rows_out = []
    weighted_wr = 0.0
    total_share = 0.0
    low_conf_share = 0.0
    for opp, share in norm_shares.items():
        # Mirror is even
        if opp == deck_archetype:
            pre = 0.50
            n = 0
            source = "mirror"
        elif opp in real_for_us:
            pre = real_for_us[opp]
            n = real_n_for_us[opp]
            source = "paper"
        elif opp in untapped_for_us:
            pre = untapped_for_us[opp]
            n = untapped_n_for_us[opp]
            source = "untapped"
        else:
            pre = 0.50
            n = 0
            source = "guess"

        diff = diff_by_opp.get(opp, "")
        bump = bumps.get(diff, 0.0) if diff else 0.0
        post = max(0.10, min(0.90, pre + bump))

        contrib = post * share
        weighted_wr += contrib
        total_share += share
        if n < 20 and source != "mirror":
            low_conf_share += share

        rows_out.append({
            "opponent":     opp,
            "share":        share,
            "pre_board_wr": pre,
            "post_board_wr": post,
            "difficulty":   diff,
            "source":       source,
            "sample_n":     n,
            "contribution": contrib,
        })

    # Normalize if total_share != 1 (e.g. field_shares didn't sum to 1)
    if total_share > 0:
        weighted_wr = weighted_wr / total_share
        low_conf_share = low_conf_share / total_share

    rows_out.sort(key=lambda r: r["contribution"], reverse=True)
    best  = [r for r in rows_out if r["post_board_wr"] > 0.55][:5]
    worst = sorted([r for r in rows_out if r["post_board_wr"] < 0.45],
                   key=lambda r: r["post_board_wr"])[:5]

    return {
        "deck_name":         deck.get("name", ""),
        "deck_archetype":    deck_archetype,
        "field_total_share": total_share,
        "field_weighted_wr": weighted_wr,
        "rows":              rows_out,
        "best":              best,
        "worst":             worst,
        "low_confidence_share": low_conf_share,
    }


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
