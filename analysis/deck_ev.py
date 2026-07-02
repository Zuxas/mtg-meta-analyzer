"""
analysis/deck_ev.py -- single-deck field-weighted EV calculator.

Lives in its own module to avoid the existing win_rates <-> field_optimizer
circular import.

compute_deck_ev(deck_id, field_shares=None, format_name='standard') combines:
  1. Paper real-match WR (mtg_meta.db matches via get_real_matchup_winrates)
  2. Untapped Bo3 matchup matrix (premium endpoint)
  3. SB difficulty bumps from saved_sb_plans:
       Easy   = +5pp to pre-board WR
       Medium = +0pp
       Hard   = -5pp

Output includes per-matchup breakdown sorted by contribution to total,
the top 5 favorable and bottom 5 unfavorable matchups, and a
low-confidence-share metric (fraction of field where n<20 matches).

Used for RC prep -- gives a concrete EV prediction for a deck against
an expected field, with the SB plan quality factored in.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from db.database import DB_PATH as CENTRAL_DB_PATH


def compute_deck_ev(
    deck_id: int,
    field_shares: Optional[dict] = None,
    format_name: str = "standard",
    pre_post_bumps: Optional[dict] = None,
) -> dict:
    """Compute expected field-weighted win rate for a saved deck."""
    from db.saved_decks import get_deck, get_sb_plans
    from analysis.archetypes import normalize as norm_arch
    from analysis.win_rates import get_real_matchup_winrates
    from db.untapped_queries import get_untapped_matchup_matrix

    deck = get_deck(deck_id)
    if not deck:
        return {"error": f"deck_id {deck_id} not found"}

    deck_archetype = norm_arch(deck.get("archetype", ""))

    # Build field_shares from 14d meta if not provided
    if field_shares is None:
        field_shares = _default_field_shares(format_name)
        if not field_shares:
            return {"error": "no recent meta data to derive field shares"}

    norm_shares: dict = {}
    for k, v in field_shares.items():
        nk = norm_arch(k)
        norm_shares[nk] = norm_shares.get(nk, 0.0) + v

    # Paper matchup matrix (bidirectional from canonical)
    real_raw = get_real_matchup_winrates(format_name, min_matches=10)
    real_for_us: dict = {}
    real_n_for_us: dict = {}
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

    # Untapped Bo3 matrix
    untapped = get_untapped_matchup_matrix(format_name)
    untapped_for_us: dict = {}
    untapped_n_for_us: dict = {}
    for opp, stats in (untapped.get(deck_archetype, {}) or {}).items():
        untapped_for_us[opp] = stats["winrate"]
        untapped_n_for_us[opp] = stats["matches"]

    bumps = pre_post_bumps or {"Easy": 0.05, "Medium": 0.0, "Hard": -0.05}
    sb_plans = get_sb_plans(deck_id)
    diff_by_opp: dict = {}
    for p in sb_plans:
        diff_by_opp[norm_arch(p.get("opponent_archetype", ""))] = \
            p.get("difficulty", "Medium")

    rows_out = []
    weighted_wr = 0.0
    total_share = 0.0
    low_conf_share = 0.0

    for opp, share in norm_shares.items():
        if opp == deck_archetype:
            pre, n, source = 0.50, 0, "mirror"
        elif opp in real_for_us:
            pre, n, source = real_for_us[opp], real_n_for_us[opp], "paper"
        elif opp in untapped_for_us:
            pre, n, source = untapped_for_us[opp], untapped_n_for_us[opp], "untapped"
        else:
            pre, n, source = 0.50, 0, "guess"

        diff = diff_by_opp.get(opp, "")
        bump = bumps.get(diff, 0.0) if diff else 0.0
        post = max(0.10, min(0.90, pre + bump))

        contrib = post * share
        weighted_wr += contrib
        total_share += share
        if n < 20 and source != "mirror":
            low_conf_share += share

        rows_out.append({
            "opponent":      opp,
            "share":         share,
            "pre_board_wr":  pre,
            "post_board_wr": post,
            "difficulty":    diff,
            "source":        source,
            "sample_n":      n,
            "contribution":  contrib,
        })

    if total_share > 0:
        weighted_wr = weighted_wr / total_share
        low_conf_share = low_conf_share / total_share

    rows_out.sort(key=lambda r: r["contribution"], reverse=True)
    best = [r for r in rows_out if r["post_board_wr"] > 0.55][:5]
    worst = sorted(
        [r for r in rows_out if r["post_board_wr"] < 0.45],
        key=lambda r: r["post_board_wr"],
    )[:5]

    return {
        "deck_name":            deck.get("name", ""),
        "deck_archetype":       deck_archetype,
        "field_total_share":    total_share,
        "field_weighted_wr":    weighted_wr,
        "rows":                 rows_out,
        "best":                 best,
        "worst":                worst,
        "low_confidence_share": low_conf_share,
    }


def _default_field_shares(format_name: str = "standard") -> dict:
    """Derive expected field shares from the last 14 days of paper data."""
    db_path = Path(CENTRAL_DB_PATH)
    since = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")

    with sqlite3.connect(str(db_path)) as con:
        total = con.execute(f"""
            SELECT COUNT(*) FROM decks d JOIN events e ON e.id=d.event_id
            WHERE lower(e.format) = ?
              AND (CASE WHEN instr(e.date,'/')>0
                THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2)
                ELSE replace(e.date,'-','') END) >= '{since}'
        """, (format_name.lower(),)).fetchone()[0]
        if total <= 0:
            return {}
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

    shares = {}
    for arch, n in rows:
        shares[arch] = n / total
    return shares
