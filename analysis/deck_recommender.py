"""
Meta-based deck recommendation engine.

Given the current meta, recommends which deck has the best expected
performance by combining matchup data, meta share, win rate, and trend.

Usage:
    from analysis.deck_recommender import recommend_deck
    result = recommend_deck("standard", top=10)
"""


def recommend_deck(format_name: str = "standard", top: int = 10,
                   weeks: int = 4) -> dict:
    """
    Recommend the best deck for the current meta.

    Uses real matchup data where available, falls back to placement-based estimates.
    Factors: weighted matchup WR against expected field, raw win rate, trend direction.

    Returns:
        {
            "format": str,
            "recommendations": [
                {
                    "archetype": str,
                    "score": float,           # 0-100 composite score
                    "matchup_wr": float,      # weighted WR vs field (0.0-1.0)
                    "raw_wr": float,          # overall win rate
                    "meta_share": float,      # current meta share
                    "trend": str,             # "rising", "falling", "stable"
                    "strengths": list[str],   # matchups favored (>55%)
                    "weaknesses": list[str],  # matchups unfavored (<45%)
                    "verdict": str,           # human-readable recommendation
                },
                ...
            ],
            "meta_snapshot": str,   # e.g. "Based on 2-week meta (1,234 decks)"
        }
    """
    from datetime import datetime, timedelta
    from analysis.win_rates import get_meta_standings

    since = datetime.now() - timedelta(weeks=weeks)
    standings = get_meta_standings(format_name, top=top, since=since)
    if not standings:
        return {"format": format_name, "recommendations": [], "meta_snapshot": "No data"}

    total_apps = sum(s["appearances"] for s in standings)

    # Build field distribution from actual meta shares
    field = {}
    for s in standings:
        count = max(1, round(s["appearances"] / max(total_apps, 1) * 100))
        field[s["archetype"]] = count

    # Get matchup-weighted win rates
    matchup_results = _get_matchup_scores(field, format_name, since)

    # Get trend data
    trends = _get_trends(standings, format_name, weeks)

    # Build recommendations
    recs = []
    for s in standings:
        arch = s["archetype"]
        raw_wr = s.get("est_match_winpct", 0.5)
        meta_share = s.get("meta_share", 0)
        mu_data = matchup_results.get(arch, {})
        matchup_wr = mu_data.get("weighted_win_rate", raw_wr)
        strengths = mu_data.get("strengths", [])
        weaknesses = mu_data.get("weaknesses", [])
        trend = trends.get(arch, "stable")

        # Composite score: matchup WR (50%) + raw WR (30%) + trend bonus (20%)
        trend_bonus = 0.55 if trend == "rising" else (0.45 if trend == "falling" else 0.5)
        score = (
            (matchup_wr or 0.5) * 50
            + raw_wr * 30
            + trend_bonus * 20
        )

        verdict = _build_verdict(arch, score, matchup_wr, trend, strengths, weaknesses)

        recs.append({
            "archetype": arch,
            "score": round(score, 1),
            "matchup_wr": round(matchup_wr, 3) if matchup_wr else None,
            "raw_wr": round(raw_wr, 3),
            "meta_share": round(meta_share, 3),
            "trend": trend,
            "strengths": strengths[:5],
            "weaknesses": weaknesses[:5],
            "verdict": verdict,
        })

    recs.sort(key=lambda r: -r["score"])

    return {
        "format": format_name,
        "recommendations": recs,
        "meta_snapshot": f"Based on {weeks}-week meta ({total_apps:,} decks)",
    }


def _get_matchup_scores(field: dict, format_name: str, since) -> dict:
    """Get weighted matchup WR for each archetype against the field."""
    results = {}
    try:
        from analysis.win_rates import get_real_matchup_winrates
        real = get_real_matchup_winrates(format_name, since=since, min_matches=10)
    except Exception:
        real = {}

    archetypes = list(field.keys())
    total_field = sum(field.values())

    for arch in archetypes:
        arch_count = field[arch]
        opp_total = total_field - arch_count
        if opp_total <= 0:
            results[arch] = {"weighted_win_rate": 0.5, "strengths": [], "weaknesses": []}
            continue

        weighted_sum = 0.0
        strengths = []
        weaknesses = []

        for opp in archetypes:
            if opp == arch:
                continue
            weight = field[opp] / opp_total

            # Look up matchup WR (canonical ordering: alphabetical)
            wr = None
            a, b = sorted([arch, opp])
            if a in real and b in real.get(a, {}):
                mu = real[a][b]
                wr = mu["win_rate"] if a == arch else (1.0 - mu["win_rate"])
            elif b in real and a in real.get(b, {}):
                mu = real[b][a]
                wr = (1.0 - mu["win_rate"]) if b == arch else mu["win_rate"]

            if wr is None:
                wr = 0.5  # no data, assume even

            weighted_sum += wr * weight

            if wr >= 0.55:
                strengths.append(opp)
            elif wr <= 0.45:
                weaknesses.append(opp)

        results[arch] = {
            "weighted_win_rate": weighted_sum,
            "strengths": strengths,
            "weaknesses": weaknesses,
        }

    return results


def _get_trends(standings: list, format_name: str, weeks: int) -> dict:
    """Get trend direction for each archetype."""
    try:
        from analysis.meta_change import compare_periods
        result = compare_periods(format_name, weeks_current=weeks, weeks_prior=weeks, top=30)
        return {a["archetype"]: a["status"] for a in result.get("archetypes", [])}
    except Exception:
        return {}


def _build_verdict(arch, score, matchup_wr, trend, strengths, weaknesses) -> str:
    parts = []

    if score >= 55:
        parts.append(f"{arch} is a top meta pick right now.")
    elif score >= 50:
        parts.append(f"{arch} is a solid choice.")
    else:
        parts.append(f"{arch} faces headwinds in this meta.")

    if trend == "rising":
        parts.append("Meta share is rising.")
    elif trend == "falling":
        parts.append("Popularity is declining.")

    if strengths:
        parts.append(f"Favored vs: {', '.join(strengths[:3])}.")
    if weaknesses:
        parts.append(f"Weak vs: {', '.join(weaknesses[:3])}.")

    return " ".join(parts)
