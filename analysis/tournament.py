"""
analysis/tournament.py — Tournament structure, RCQ equity, and breaker math.

Official RCQ rules (WPN / MTR Appendix E):
    • Minimum 8 players required to run an RCQ
    • Decklists required at ALL RCQ events (Competitive REL)
    • Round counts per Appendix E:
        8 players  = 3 rounds, single elimination bracket (all 8 play)
        9-16       = 4 rounds Swiss + top 4
        17-32      = 5 rounds Swiss + top 8
        33-64      = 6 rounds Swiss + top 8
        65-128     = 7 rounds Swiss + top 8
        129+       = 8 rounds Swiss + top 8

Public functions:
    tournament_structure(players)              -> dict
    record_pts(wins, draws)                    -> int
    standing_analysis(wins, losses, draws, players) -> dict
    id_recommendation(my_w, my_l, my_d, op_w, op_l, op_d, players) -> dict
    rcq_equity(my_archetype, field, format_name, ...) -> dict
"""
import math
from functools import lru_cache

# ---------------------------------------------------------------------------
# RCQ constants (official WPN rules)
# ---------------------------------------------------------------------------

RCQ_MIN_PLAYERS = 8
RCQ_COMP_REL    = True   # Always Competitive Rules Enforcement Level
RCQ_DECKLISTS   = True   # Decklists required at all RCQ events


# ---------------------------------------------------------------------------
# Tournament structure  (MTR Appendix E)
# ---------------------------------------------------------------------------

def swiss_rounds(players: int) -> int:
    """Round count per MTR Appendix E.  For >256 players, ceil(log2(n))."""
    if players <= 8:   return 3
    if players <= 16:  return 4
    if players <= 32:  return 5
    if players <= 64:  return 6
    if players <= 128: return 7
    if players <= 226: return 8
    return max(8, math.ceil(math.log2(players)))


def top_cut_size(players: int) -> int:
    """Top-cut bracket per MTR Appendix E.
    8 players = single elimination bracket (all 8 play, no separate cut).
    9-16      = top 4.
    17+       = top 8.
    """
    if players == 8:  return 8   # single elimination — all 8 play
    if players <= 16: return 4   # 9-16 → top 4
    return 8                      # 17+ → top 8


def cut_threshold(rounds: int) -> int:
    """Minimum points that reliably make top cut (well-known DCI benchmarks).

    For ≤8 rounds: official WPN guidelines.
    For 9+: standard heuristic is rounds*3 - 6 (i.e. X-2 record or better).
    """
    known = {3: 6, 4: 9, 5: 12, 6: 15, 7: 18, 8: 21}
    if rounds in known:
        return known[rounds]
    # Large events: X-2 or X-3 typically makes top 8
    return max(known.get(8, 21), rounds * 3 - 6)


# ---------------------------------------------------------------------------
# Hypergeometric encounter probability
# ---------------------------------------------------------------------------

def encounter_probability(total_opponents: int, archetype_count: int,
                          rounds: int) -> list[float]:
    """
    Probability of facing an archetype exactly k times in `rounds` rounds,
    given `archetype_count` copies in a field of `total_opponents`.

    Uses the hypergeometric distribution:
        P(X=k) = C(K,k) * C(N-K, n-k) / C(N, n)

    where N = total_opponents, K = archetype_count, n = rounds.

    Returns list of length (rounds+1): [P(0), P(1), P(2), ..., P(rounds)]
    """
    N = total_opponents
    K = min(archetype_count, N)
    n = min(rounds, N)

    probs = []
    for k in range(n + 1):
        if k > K or (n - k) > (N - K):
            probs.append(0.0)
        else:
            p = (math.comb(K, k) * math.comb(N - K, n - k)
                 / math.comb(N, n))
            probs.append(p)

    return probs


def encounter_summary(total_opponents: int, archetype_count: int,
                      rounds: int) -> dict:
    """
    Summarized encounter probability for display.

    Returns dict with:
        probs:        full probability list [P(0), P(1), ...]
        expected:     expected number of times you face this archetype
        p_zero:       probability of never facing it
        p_at_least_1: probability of facing it at least once
        p_at_least_2: probability of facing it 2+ times
        mode:         most likely encounter count
        mode_pct:     probability of the mode
    """
    probs = encounter_probability(total_opponents, archetype_count, rounds)
    expected = sum(k * p for k, p in enumerate(probs))
    p_zero = probs[0] if probs else 1.0
    p_at_least_1 = 1.0 - p_zero
    p_at_least_2 = 1.0 - p_zero - (probs[1] if len(probs) > 1 else 0.0)

    mode = max(range(len(probs)), key=lambda k: probs[k]) if probs else 0
    mode_pct = probs[mode] if probs else 0.0

    return {
        "probs": probs,
        "expected": round(expected, 2),
        "p_zero": round(p_zero, 3),
        "p_at_least_1": round(p_at_least_1, 3),
        "p_at_least_2": round(max(p_at_least_2, 0.0), 3),
        "mode": mode,
        "mode_pct": round(mode_pct, 3),
    }


def tournament_structure(players: int) -> dict:
    rounds     = swiss_rounds(players)
    top_cut    = top_cut_size(players)
    single_elim = (players == 8)
    return {
        "players":     players,
        "rounds":      rounds,
        "top_cut":     top_cut,
        "threshold":   0 if single_elim else cut_threshold(rounds),
        "single_elim": single_elim,
        "rcq_legal":   players >= RCQ_MIN_PLAYERS,
    }


# ---------------------------------------------------------------------------
# Event presets  (RCQ / RC / PTQ / Custom)
# ---------------------------------------------------------------------------

EVENT_PRESETS = {
    "RCQ": {
        "players_range": (32, 128),
        "default_players": 48,
        "top_cut": 8,
        "rounds": None,      # auto from swiss_rounds()
    },
    "Regional Championship": {
        "players_range": (200, 800),
        "default_players": 400,
        "top_cut": 8,
        "rounds": None,      # auto, typically 9-10
    },
    "Pro Tour Qualifier / Open": {
        "players_range": (500, 2000),
        "default_players": 800,
        "top_cut": 8,
        "rounds": None,      # auto, typically 13-15
    },
    "Custom": {
        "players_range": (4, 5000),
        "default_players": 64,
        "top_cut": 8,
        "rounds": None,
    },
}


# ---------------------------------------------------------------------------
# 2-day event math
# ---------------------------------------------------------------------------

def x_loss_cutoff(players: int, rounds: int, top_cut: int = 8) -> int:
    """Minimum match wins needed to make top cut (max losses you can take).

    Returns the number of losses.  e.g. x_loss_cutoff(800, 15, 8) → 3
    means you need a 12-3 record or better.
    """
    # Well-known DCI heuristic: top_cut / players ≈ fraction that make it
    # In Swiss, X-Y record where X = rounds - Y.  Need points >= threshold.
    thr = cut_threshold(rounds)
    # Minimum wins = ceil(threshold / 3) assuming no draws
    min_wins = math.ceil(thr / 3)
    return max(0, rounds - min_wins)


def day2_conversion_probability(
    win_rate: float, day1_rounds: int, min_record_wins: int,
) -> float:
    """Probability of achieving at least min_record_wins in day1_rounds.

    Uses binomial distribution.  Assumes no draws for simplicity.
    """
    p = 0.0
    for k in range(min_record_wins, day1_rounds + 1):
        p += math.comb(day1_rounds, k) * win_rate**k * (1 - win_rate)**(day1_rounds - k)
    return round(max(0.0, min(1.0, p)), 4)


# ---------------------------------------------------------------------------
# Points helpers
# ---------------------------------------------------------------------------

def record_pts(wins: int, draws: int = 0) -> int:
    return wins * 3 + draws


# ---------------------------------------------------------------------------
# Breaker math — pure calculations, no DB required
# ---------------------------------------------------------------------------

def standing_analysis(wins: int, losses: int, draws: int, players: int) -> dict:
    """
    Analyse current tournament standing and calculate draw/win scenarios.

    Returns a dict with:
      record, played, remaining, cur_pts, max_pts, threshold, top_cut, rounds,
      eliminated, safe_to_draw, must_win, status, status_color,
      draw: {pts, viable, wins_needed, remaining},
      win:  {pts, viable, wins_needed, remaining},
      alive_records: list of {record, points, over}
    """
    struct    = tournament_structure(players)
    rounds    = struct["rounds"]
    thr       = struct["threshold"]
    played    = wins + losses + draws
    remaining = max(0, rounds - played)
    cur_pts   = record_pts(wins, draws)
    max_pts   = cur_pts + remaining * 3

    can_make  = max_pts >= thr

    # Draw scenario
    d_pts = cur_pts + 1
    d_rem = max(0, remaining - 1)
    d_max = d_pts + d_rem * 3
    d_ok  = d_max >= thr
    d_wn  = min(d_rem, max(0, math.ceil((thr - d_pts) / 3)))

    # Win scenario
    w_pts = cur_pts + 3
    w_rem = max(0, remaining - 1)
    w_max = w_pts + w_rem * 3
    w_ok  = w_max >= thr
    w_wn  = min(w_rem, max(0, math.ceil((thr - w_pts) / 3)))

    # All alive finish records from current position
    alive = []
    for ew in range(remaining + 1):
        for ed in range(remaining - ew + 1):
            el = remaining - ew - ed
            fp = cur_pts + ew * 3 + ed
            if fp >= thr:
                alive.append({
                    "record": f"{wins+ew}-{losses+el}-{draws+ed}",
                    "points": fp,
                    "over":   fp > thr,
                })
    alive.sort(key=lambda x: (-x["points"], x["record"]))

    # Status
    if not can_make:
        status, sc = "ELIMINATED", "#e6194b"
    elif cur_pts >= thr and remaining == 0:
        status, sc = "LOCKED IN", "#3cb44b"
    elif d_ok and draws == 0 and remaining > 0:
        status, sc = "SAFE TO DRAW", "#3cb44b"
    elif d_ok and remaining > 0:
        status, sc = "CAN DRAW", "#3cb44b"
    else:
        status, sc = "MUST WIN", "#f58231"

    return {
        "record":       f"{wins}-{losses}-{draws}",
        "played":       played,
        "remaining":    remaining,
        "cur_pts":      cur_pts,
        "max_pts":      max_pts,
        "threshold":    thr,
        "top_cut":      struct["top_cut"],
        "rounds":       rounds,
        "eliminated":   not can_make,
        "safe_to_draw": d_ok,
        "must_win":     not d_ok and can_make,
        "status":       status,
        "status_color": sc,
        "draw": {"pts": d_pts, "viable": d_ok, "wins_needed": d_wn, "remaining": d_rem},
        "win":  {"pts": w_pts, "viable": w_ok, "wins_needed": w_wn, "remaining": w_rem},
        "alive_records": alive[:20],
    }


def id_recommendation(
    my_w: int, my_l: int, my_d: int,
    op_w: int, op_l: int, op_d: int,
    players: int,
) -> dict:
    """Should two players ID? Returns analysis for both + a plain-English recommendation."""
    me  = standing_analysis(my_w, my_l, my_d, players)
    opp = standing_analysis(op_w, op_l, op_d, players)

    if me["eliminated"] and opp["eliminated"]:
        rec, rc = "Both players are eliminated — play for fun, result doesn't matter.", "#888888"
    elif me["eliminated"]:
        rec, rc = "You are eliminated. Play the round — you have nothing to lose.", "#888888"
    elif opp["eliminated"]:
        rec, rc = "Opponent is eliminated. You can safely draw or win — either is fine.", "#3cb44b"
    elif me["safe_to_draw"] and opp["safe_to_draw"]:
        rec, rc = "Both players are safely drawing into top cut. ID is correct.", "#3cb44b"
    elif me["safe_to_draw"] and not opp["safe_to_draw"]:
        rec, rc = ("You can safely draw, but your opponent needs a win. "
                   "They are unlikely to accept an ID offer."), "#f58231"
    elif not me["safe_to_draw"] and opp["safe_to_draw"]:
        rec, rc = ("Your opponent can safely draw but YOU need a win. "
                   "Do NOT accept any ID offer — play for the win."), "#e6194b"
    else:
        rec, rc = ("Neither player is safely in. Both should play for the win. "
                   "An ID benefits neither player."), "#e6194b"

    return {"me": me, "opponent": opp, "recommendation": rec, "rec_color": rc}


# ---------------------------------------------------------------------------
# RCQ Equity Calculator
# ---------------------------------------------------------------------------

def _elo_matchup(my_str: float, op_str: float) -> float:
    total = my_str + op_str
    return (my_str / total) if total > 0 else 0.5


def rcq_equity(
    my_archetype: str,
    field: dict,
    format_name: str = "standard",
    since=None,
    until=None,
) -> dict:
    """
    Calculate RCQ tournament equity for my_archetype against a specified field.

    field: {archetype_name: count}

    Returns weighted win rate, top-8 probability, positioning grade,
    matchup breakdown, and sideboard recommendations.
    """
    from analysis.win_rates import get_meta_standings

    standings = get_meta_standings(format_name, top=60, since=since, until=until)
    wr_map = {s["archetype"].lower(): s["est_match_winpct"] for s in standings}

    def _wr(name: str) -> float:
        nl = name.lower()
        if nl in wr_map:
            return wr_map[nl]
        for k, v in wr_map.items():
            if nl in k or k in nl:
                return v
        return 0.50

    my_wr     = _wr(my_archetype)
    total_opp = sum(field.values())
    if total_opp == 0:
        return {"error": "No field specified"}

    players  = total_opp + 1
    struct   = tournament_structure(players)
    rounds   = struct["rounds"]
    thr      = struct["threshold"]
    min_wins = (thr + 2) // 3   # ceiling wins needed

    from analysis.sideboard_guides import (
        get_matchup_guides, estimate_postboard_wr, flip_analysis,
    )

    matchups     = []
    weighted_sum = 0.0

    for arch, count in field.items():
        op_wr  = _wr(arch)
        mu_wr  = _elo_matchup(my_wr, op_wr)
        frac   = count / total_opp
        weighted_sum += mu_wr * frac

        # Guide-based post-board analysis
        guide_data = get_matchup_guides(my_archetype, arch, format_name)
        has_data   = guide_data["my_count"] > 0 or guide_data["opp_count"] > 0
        my_sb_in   = guide_data["my_sb_plan"]["total_in"]
        opp_sb_in  = guide_data["opp_sb_plan"]["total_in"]
        g23_wr     = estimate_postboard_wr(mu_wr, my_sb_in, opp_sb_in) if has_data else mu_wr
        flip       = flip_analysis(mu_wr, g23_wr, has_guide_data=has_data)

        enc = encounter_summary(total_opp, count, rounds)

        matchups.append({
            "archetype":  arch,
            "count":      count,
            "frac":       round(frac, 3),
            "exp_rounds": round(rounds * frac, 2),
            "matchup_wr": round(mu_wr, 3),
            "g1_wr":      round(mu_wr, 3),
            "g23_wr":     round(g23_wr, 3),
            "favored":    mu_wr >= 0.52,
            "unfavored":  mu_wr <= 0.48,
            "guide_data": guide_data,
            "flip":       flip,
            "encounter":  enc,
        })

    matchups.sort(key=lambda m: m["exp_rounds"], reverse=True)
    wwr = weighted_sum

    # Binomial P(making top cut)
    top_prob = sum(
        math.comb(rounds, k) * wwr**k * (1 - wwr)**(rounds - k)
        for k in range(min_wins, rounds + 1)
    )
    top_prob = max(0.0, min(1.0, top_prob))

    # Positioning grade
    if wwr >= 0.57:   grade, glabel = "A+", "Excellent positioning"
    elif wwr >= 0.54: grade, glabel = "A",  "Very good positioning"
    elif wwr >= 0.52: grade, glabel = "B",  "Good positioning"
    elif wwr >= 0.50: grade, glabel = "C",  "Average positioning"
    elif wwr >= 0.47: grade, glabel = "D",  "Below average positioning"
    else:             grade, glabel = "F",  "Poor — consider a different deck"

    # Sideboard recommendations — now guide-aware
    recs = []
    # Flipped matchups are the most critical warning
    flipped = [m for m in matchups if m["flip"]["flipped"] and m["favored"] and m["flip"]["delta"] < 0]
    for m in sorted(flipped, key=lambda x: x["flip"]["delta"]):
        recs.append(
            f"\u26a0 FLIP WARNING — {m['archetype']}: "
            f"Favored G1 ({m['g1_wr']*100:.0f}%) but opponent sideboard "
            f"flips this post-board ({m['g23_wr']*100:.0f}% G2/G3). "
            f"Address their {m['guide_data']['opp_sb_plan']['total_in']} hate cards."
        )

    # Significantly worse post-board without full flip
    sig_worse = [
        m for m in matchups
        if m["flip"]["significantly_worse"] and not m["flip"]["flipped"]
        and m["guide_data"]["opp_count"] > 0
    ]
    for m in sorted(sig_worse, key=lambda x: x["flip"]["delta"]):
        recs.append(
            f"Post-board danger — {m['archetype']}: "
            f"{m['g1_wr']*100:.0f}% G1 drops to {m['g23_wr']*100:.0f}% G2/G3. "
            f"Opponent has {m['guide_data']['opp_sb_plan']['total_in']} dedicated cards vs you."
        )

    # Standard unfavored without guide data
    bad  = sorted([m for m in matchups if m["unfavored"] and not m["flip"]["has_data"]],
                  key=lambda m: -m["frac"])
    good = sorted([m for m in matchups if m["favored"]],   key=lambda m: -m["frac"])

    for m in bad[:3]:
        recs.append(
            f"Sideboard heavily for {m['archetype']} "
            f"(~{m['exp_rounds']:.1f} expected rounds, {m['matchup_wr']*100:.0f}% WR)"
        )
    for m in good[:2]:
        if not m["flip"]["flipped"]:
            recs.append(
                f"Don't over-board vs {m['archetype']} "
                f"— already favored at {m['matchup_wr']*100:.0f}% WR"
            )
    if not recs:
        recs.append("Field looks balanced — focus on clean execution and game-1 win rate.")

    return {
        "my_archetype": my_archetype,
        "my_wr":        round(my_wr, 3),
        "field":        field,
        "players":      players,
        "struct":       struct,
        "weighted_wr":  round(wwr, 3),
        "top_prob":     round(top_prob, 3),
        "grade":        grade,
        "grade_label":  glabel,
        "matchups":     matchups,
        "recs":         recs,
    }
