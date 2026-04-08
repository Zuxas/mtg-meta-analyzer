"""
Matchup advisor — identifies underperforming matchups and suggests SB adjustments.

Combines personal match log win rates with meta expected WRs,
guide recommendations, and saved SB plans to give actionable advice.

Usage:
    from analysis.matchup_advisor import get_advice
    advice = get_advice("Boros Energy", "standard", my_deck_id=5)
"""


def get_advice(my_archetype: str, format_name: str = "standard",
               my_deck_id: int = None, since: str = None) -> dict:
    """
    Generate sideboard advice for matchups where the user is underperforming.

    Returns:
        {
            "archetype": str,
            "format": str,
            "matchups": [
                {
                    "opponent": str,
                    "personal_wr": float,
                    "meta_wr": float | None,
                    "delta": float | None,
                    "matches_played": int,
                    "play_wr": float | None,
                    "draw_wr": float | None,
                    "severity": str,          # "critical", "warning", "ok", "strong"
                    "has_sb_plan": bool,
                    "guide_available": bool,
                    "suggestion": str,
                    "guide_in": list[str],
                    "guide_out": list[str],
                },
                ...
            ],
            "summary": str,
        }
    """
    from db.match_log import get_matchup_stats
    from analysis.archetypes import normalize as norm_arch

    stats = get_matchup_stats(my_archetype, format_name, since)
    if not stats:
        return {
            "archetype": my_archetype, "format": format_name,
            "matchups": [],
            "summary": "No match data logged yet. Play some games and log results first.",
        }

    meta_wrs = _get_meta_wrs(my_archetype, format_name)
    saved_plans = _get_saved_plans(my_deck_id) if my_deck_id else {}

    matchups = []
    for opp, s in sorted(stats.items(), key=lambda x: x[1]["wr"]):
        personal_wr = s["wr"]
        matches = s["total"]
        if matches < 2:
            continue

        opp_norm = norm_arch(opp)
        meta_wr = meta_wrs.get(opp_norm)
        delta = (personal_wr - meta_wr) if meta_wr is not None else None

        if delta is not None and delta <= -0.10 and matches >= 5:
            severity = "critical"
        elif delta is not None and delta <= -0.05:
            severity = "warning"
        elif personal_wr >= 0.60:
            severity = "strong"
        else:
            severity = "ok"

        has_plan = opp_norm in saved_plans or opp in saved_plans
        guide_in, guide_out, guide_available = _get_guide_advice(
            my_archetype, opp, format_name
        )

        suggestion = _build_suggestion(
            opp, personal_wr, meta_wr, delta, matches,
            s.get("play_wr"), s.get("draw_wr"),
            has_plan, guide_available, guide_in,
        )

        matchups.append({
            "opponent": opp,
            "personal_wr": round(personal_wr, 3),
            "meta_wr": round(meta_wr, 3) if meta_wr is not None else None,
            "delta": round(delta, 3) if delta is not None else None,
            "matches_played": matches,
            "play_wr": s.get("play_wr"),
            "draw_wr": s.get("draw_wr"),
            "severity": severity,
            "has_sb_plan": has_plan,
            "guide_available": guide_available,
            "suggestion": suggestion,
            "guide_in": guide_in,
            "guide_out": guide_out,
        })

    _sev = {"critical": 0, "warning": 1, "ok": 2, "strong": 3}
    matchups.sort(key=lambda m: (_sev.get(m["severity"], 2), m["personal_wr"]))

    critical = sum(1 for m in matchups if m["severity"] == "critical")
    warnings = sum(1 for m in matchups if m["severity"] == "warning")
    strong = sum(1 for m in matchups if m["severity"] == "strong")

    if critical:
        summary = (f"{critical} critical matchup{'s' if critical != 1 else ''} "
                   f"significantly below meta. Review your sideboard plan.")
    elif warnings:
        summary = (f"{warnings} matchup{'s' if warnings != 1 else ''} "
                   f"slightly below expected. Consider SB adjustments.")
    else:
        summary = f"Looking solid — {strong} strong matchups."

    return {
        "archetype": my_archetype, "format": format_name,
        "matchups": matchups, "summary": summary,
    }


def _get_meta_wrs(archetype: str, format_name: str) -> dict:
    try:
        from analysis.win_rates import get_real_matchup_winrates
        from analysis.archetypes import normalize as norm_arch
        real = get_real_matchup_winrates(format_name, min_matches=10)
        result = {}
        arch_norm = norm_arch(archetype)
        for a, opps in real.items():
            for b, stats in opps.items():
                if norm_arch(a) == arch_norm:
                    result[norm_arch(b)] = stats["win_rate"]
                elif norm_arch(b) == arch_norm:
                    result[norm_arch(a)] = 1.0 - stats["win_rate"]
        return result
    except Exception:
        return {}


def _get_saved_plans(deck_id: int) -> dict:
    try:
        from db.saved_decks import get_sb_plans
        return {p["opponent_archetype"]: p for p in get_sb_plans(deck_id)}
    except Exception:
        return {}


def _get_guide_advice(my_arch, opp_arch, format_name):
    try:
        from analysis.sideboard_guides import get_matchup_guides
        guides = get_matchup_guides(my_arch, opp_arch, format_name)
        plan = guides.get("my_sb_plan", {})
        if plan:
            in_cards = [f"{q}x {n}" for q, n in plan.get("in", [])]
            out_cards = [f"{q}x {n}" for q, n in plan.get("out", [])]
            return in_cards[:6], out_cards[:6], True
    except Exception:
        pass
    return [], [], False


def _build_suggestion(opp, wr, meta_wr, delta, matches,
                      play_wr, draw_wr, has_plan, has_guide, guide_in):
    parts = []

    if delta is not None and delta <= -0.10:
        parts.append(f"Your WR vs {opp} is {delta*100:+.0f}% below meta.")
    elif delta is not None and delta <= -0.05:
        parts.append(f"Slightly below expected vs {opp} ({delta*100:+.0f}%).")

    if play_wr is not None and draw_wr is not None:
        if play_wr - draw_wr > 0.15:
            parts.append("Much better on the play — consider play-focused SB cards.")
        elif draw_wr - play_wr > 0.15:
            parts.append("Better on the draw — your draw SB plan may need work.")

    if not has_plan and not has_guide:
        parts.append("No SB plan or guide — create one in My Decks.")
    elif not has_plan and has_guide:
        parts.append("Guide available — save a SB plan based on it.")
        if guide_in:
            parts.append(f"Guide: IN {', '.join(guide_in[:3])}")
    elif has_plan and delta and delta <= -0.05:
        parts.append("SB plan exists but results still low — review it.")

    if not parts:
        if wr >= 0.60:
            parts.append(f"Strong ({wr*100:.0f}%). Keep it up.")
        else:
            parts.append("On track with meta.")

    return " ".join(parts)
