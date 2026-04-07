"""
Meta scoring: prep priority ranking and trap deck detection.

Combines meta share and win rate into actionable labels for tournament
preparation.  Pure arithmetic on data already produced by win_rates.py —
no database access, no UI coupling.

Statuses:
    Meta Pillar      — high share AND high win rate (the decks to beat)
    Trap Deck        — popular but loses (avoid or exploit)
    Underplayed      — low share but high win rate (sleeper pick)
    Fringe           — low share, middling win rate (niche viable)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Thresholds (fraction-based, not percentages)
# ---------------------------------------------------------------------------

_HIGH_SHARE = 0.05      # ≥5% meta share
_LOW_SHARE  = 0.03      # <3% meta share
_HIGH_WR    = 0.54      # ≥54% win rate
_LOW_WR     = 0.48      # <48% win rate


def classify_status(meta_share: float, win_rate: float) -> tuple[str, str]:
    """Return (status_label, color_hex) for an archetype.

    Parameters
    ----------
    meta_share : float   0-1 fraction of the field
    win_rate   : float   0-1 match win rate (real or estimated)
    """
    if meta_share >= _HIGH_SHARE and win_rate >= _HIGH_WR:
        return "Pillar", "#3cb44b"       # green
    if meta_share >= _HIGH_SHARE and win_rate < _LOW_WR:
        return "Trap", "#e6194b"         # red
    if meta_share < _LOW_SHARE and win_rate >= _HIGH_WR:
        return "Underplayed", "#f0c040"  # gold
    return "Fringe", "#888888"           # grey


def prep_priority(meta_share: float, win_rate: float) -> float:
    """Compute a 0-100 prep priority score.

    Higher = more important to have a plan against.  Weighted blend of
    how often you'll face the deck (share) and how dangerous it is (WR).
    """
    # Normalise win rate to 0-1 range assuming realistic bounds 35%-65%
    wr_norm = max(0.0, min(1.0, (win_rate - 0.35) / 0.30))
    share_norm = min(1.0, meta_share / 0.15)   # cap at 15% share
    return round((share_norm * 0.6 + wr_norm * 0.4) * 100, 1)


def score_standings(standings: list[dict],
                    real_wrs: dict | None = None) -> list[dict]:
    """Enrich a standings list with prep priority and status.

    Parameters
    ----------
    standings : list of dicts from get_meta_standings()
    real_wrs  : optional dict {archetype: {win_rate, wins, losses, ...}}
                from get_real_archetype_winrates()

    Returns the same list, each dict gaining:
        prep_priority  : float 0-100
        status         : str   (Pillar / Trap / Underplayed / Fringe)
        status_color   : str   hex color
    """
    total_apps = sum(s["appearances"] for s in standings) or 1

    for s in standings:
        share = s["appearances"] / total_apps

        # Prefer real match win rate, fall back to estimated
        real = (real_wrs or {}).get(s["archetype"])
        wr = real["win_rate"] if real else (s.get("est_match_winpct") or 0.5)

        s["prep_priority"] = prep_priority(share, wr)
        s["status"], s["status_color"] = classify_status(share, wr)

    return standings
