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
     Default path applies the bump flat to the MATCH win rate. With
     use_match_math=True the bump is applied to the POST-BOARD GAME win rate
     q implied by the observed match WR (game-1 held at the observed match
     WR -- scraped rows are match-level only) and the Bo3 is recomposed via
     analysis.match_math (Chapin MG-12). Every row also carries
     required_q_for_even: the post-board game WR needed to reach 50%.

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
from db.helpers import SQL_NORM_DATE


def _game_one_prior() -> dict:
    """Global game-1 win rate from the user's own match_log ({p1, n}).

    A GLOBAL prior, not per matchup: game-level results exist only in
    match_log (~100 rows), far too thin to split by opponent. Reported for
    the UI; the per-row math holds p1 at the observed match WR because the
    scraped matchup rows have no game-level data at all.
    """
    try:
        with sqlite3.connect(str(CENTRAL_DB_PATH)) as con:
            wins, n = con.execute(
                "SELECT SUM(CASE WHEN g1_result='win' THEN 1 ELSE 0 END), COUNT(*) "
                "FROM match_log WHERE g1_result IN ('win','loss')"
            ).fetchone()
    except sqlite3.Error:
        return {"p1": None, "n": 0}
    n = int(n or 0)
    return {"p1": (wins / n) if n else None, "n": n}


def compute_deck_ev(
    deck_id: int,
    field_shares: Optional[dict] = None,
    format_name: str = "standard",
    pre_post_bumps: Optional[dict] = None,
    use_match_math: bool = False,
) -> dict:
    """Compute expected field-weighted win rate for a saved deck.

    use_match_math=False (default, one release): the sideboard bump is added
    flat to the match win rate, as before. True: the bump is applied to the
    post-board game win rate and the Bo3 recomposed (analysis.match_math);
    each row's `math` field says which path produced its post_board_wr so
    the two can be compared side by side.
    """
    from db.saved_decks import get_deck, get_sb_plans
    from analysis.archetypes import normalize as norm_arch
    from analysis.win_rates import get_real_matchup_winrates
    from db.untapped_queries import get_untapped_matchup_matrix
    from analysis.match_math import implied_q, match_winrate, required_q

    deck = get_deck(deck_id)
    if not deck:
        return {"error": f"deck_id {deck_id} not found"}

    deck_archetype = norm_arch(deck.get("archetype", ""))

    # Build field_shares from 14d meta if not provided
    field_source = "explicit"
    if field_shares is None:
        field_shares, field_source = _default_field_shares(format_name)
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

        # Game-1 held at the observed match WR: the scraped rows are
        # match-level only, so p1 and q are not separately observable.
        p1 = pre
        q = implied_q(p1, pre)
        req_q = required_q(p1, 0.50)
        if use_match_math and q is not None:
            q_post = max(0.10, min(0.90, q + bump))
            post = match_winrate(p1, q_post)
            math_path = "implied-q"
        else:
            post = max(0.10, min(0.90, pre + bump))
            math_path = "flat-bump"

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
            "math":          math_path,
            "p1":            p1,
            "implied_q":     q,
            "required_q_for_even": req_q,
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
        "use_match_math":       use_match_math,
        "g1_prior":             _game_one_prior(),
        "field_source":         field_source,
    }


def _default_field_shares(format_name: str = "standard", *, con=None) -> tuple[dict, str | None]:
    """
    Expected field shares for the last 14 days -> (shares, source).

    Source "decks-14d" = the decks table (MTGTop8 / MTGO decklists). When that
    window is empty -- Modern's was, for weeks, while the MTGTop8 backfill was
    unrunnable -- fall back to "matches-14d": distinct (event, player) field
    shares from the melee matches table via analysis.conversion. (None, {})
    when neither has rows. `con` is injectable for tests.
    """
    since = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    norm_date = SQL_NORM_DATE.format(col="e.date")   # ISO for both stored shapes

    own = con is None
    if own:
        con = sqlite3.connect(str(Path(CENTRAL_DB_PATH)))
    try:
        total = con.execute(f"""
            SELECT COUNT(*) FROM decks d JOIN events e ON e.id=d.event_id
            WHERE lower(e.format) = ?
              AND {norm_date} >= '{since}'
        """, (format_name.lower(),)).fetchone()[0]
        if total > 0:
            rows = con.execute(f"""
                SELECT d.archetype, COUNT(*) as n
                FROM decks d JOIN events e ON e.id=d.event_id
                WHERE lower(e.format) = ?
                  AND {norm_date} >= '{since}'
                GROUP BY d.archetype HAVING n >= ?
                ORDER BY n DESC
            """, (format_name.lower(), max(3, total // 100))).fetchall()
            return {arch: n / total for arch, n in rows}, "decks-14d"

        from analysis.conversion import conversion_by_archetype
        conv = conversion_by_archetype(format_name, since, con=con)
        if conv:
            return {arch: r["field_share"] for arch, r in conv.items()}, "matches-14d"
        return {}, None
    finally:
        if own:
            con.close()
