"""
Meta change detection — compare two time periods to identify shifts.

Usage:
    from analysis.meta_change import compare_periods
    result = compare_periods("standard", weeks_current=2, weeks_prior=2)
    # Returns rising, falling, new, and gone archetypes with deltas.
"""

from datetime import datetime, timedelta


def compare_periods(format_name: str = "standard",
                    weeks_current: int = 2, weeks_prior: int = 2,
                    top: int = 30, min_appearances: int = 2) -> dict:
    """
    Compare the current meta window against the immediately prior window.

    Args:
        format_name: Format to analyze.
        weeks_current: Duration of the "current" window (most recent N weeks).
        weeks_prior: Duration of the "prior" window (N weeks before current).
        top: Max archetypes to consider per period.
        min_appearances: Minimum appearances to include an archetype.

    Returns:
        {
            "format": str,
            "current_label": str,        # e.g. "Last 2 weeks"
            "prior_label": str,          # e.g. "2-4 weeks ago"
            "archetypes": [
                {
                    "archetype": str,
                    "current_share": float,     # 0.0-1.0
                    "prior_share": float,       # 0.0-1.0
                    "share_delta": float,       # current - prior
                    "current_wr": float | None,
                    "prior_wr": float | None,
                    "wr_delta": float | None,
                    "current_apps": int,
                    "prior_apps": int,
                    "status": str,              # "rising", "falling", "stable", "new", "gone"
                },
                ...
            ],
            "summary": {
                "rising": int,
                "falling": int,
                "new": int,
                "gone": int,
                "stable": int,
            },
        }
    """
    from analysis.win_rates import get_meta_standings

    now = datetime.now()
    current_since = now - timedelta(weeks=weeks_current)
    prior_until = current_since
    prior_since = prior_until - timedelta(weeks=weeks_prior)

    current = get_meta_standings(
        format_name, top=top, min_appearances=min_appearances,
        since=current_since, until=now,
    )
    prior = get_meta_standings(
        format_name, top=top, min_appearances=min_appearances,
        since=prior_since, until=prior_until,
    )

    current_map = {s["archetype"]: s for s in current}
    prior_map = {s["archetype"]: s for s in prior}
    all_archs = sorted(set(current_map) | set(prior_map))

    results = []
    for arch in all_archs:
        c = current_map.get(arch)
        p = prior_map.get(arch)

        c_share = c["meta_share"] if c else 0.0
        p_share = p["meta_share"] if p else 0.0
        c_wr = c.get("est_match_winpct") if c else None
        p_wr = p.get("est_match_winpct") if p else None
        c_apps = c["appearances"] if c else 0
        p_apps = p["appearances"] if p else 0

        delta = c_share - p_share
        wr_delta = None
        if c_wr is not None and p_wr is not None:
            wr_delta = c_wr - p_wr

        # Classify change
        if c and not p:
            status = "new"
        elif p and not c:
            status = "gone"
        elif abs(delta) < 0.005:
            status = "stable"
        elif delta > 0:
            status = "rising"
        else:
            status = "falling"

        results.append({
            "archetype": arch,
            "current_share": round(c_share, 4),
            "prior_share": round(p_share, 4),
            "share_delta": round(delta, 4),
            "current_wr": round(c_wr, 4) if c_wr is not None else None,
            "prior_wr": round(p_wr, 4) if p_wr is not None else None,
            "wr_delta": round(wr_delta, 4) if wr_delta is not None else None,
            "current_apps": c_apps,
            "prior_apps": p_apps,
            "status": status,
        })

    # Sort: biggest gainers first, then biggest losers, then stable
    results.sort(key=lambda r: -r["share_delta"])

    counts = {"rising": 0, "falling": 0, "new": 0, "gone": 0, "stable": 0}
    for r in results:
        counts[r["status"]] += 1

    return {
        "format": format_name,
        "current_label": f"Last {weeks_current} week{'s' if weeks_current != 1 else ''}",
        "prior_label": f"{weeks_current}-{weeks_current + weeks_prior} weeks ago",
        "archetypes": results,
        "summary": counts,
    }
