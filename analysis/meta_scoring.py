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
    Cascade          — (opt-in, needs a conversion ratio) played a lot, ~50% WR,
                       and its top-cut share is explained by its field share
                       (Chapin IC-02). Popular because it is popular.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Thresholds (fraction-based, not percentages)
# ---------------------------------------------------------------------------

_HIGH_SHARE = 0.05      # ≥5% meta share
_LOW_SHARE  = 0.03      # <3% meta share
_HIGH_WR    = 0.54      # ≥54% win rate
_LOW_WR     = 0.48      # <48% win rate

# Cascade axis (analysis/conversion.py). A deck at ~50% is neither Pillar nor
# Trap, so before 2026-09-20 it was labelled Fringe or nothing; conversion
# ratio adds the missing test: presence explained by popularity alone.
_CASCADE_SHARE      = 0.03   # ≥3% of the field
_CASCADE_CONVERSION = 1.02   # top-cut share / field share ≤ 1.02
_CASCADE_WR         = (0.48, 0.52)
CASCADE_COLOR       = "#e67e22"


def classify_status(meta_share: float, win_rate: float,
                    conversion: float | None = None) -> tuple[str, str]:
    """Return (status_label, color_hex) for an archetype.

    Parameters
    ----------
    meta_share : float   0-1 fraction of the field
    win_rate   : float   0-1 match win rate (real or estimated)
    conversion : float, optional -- top-cut share / field share from
                 analysis.conversion.conversion_by_archetype(). When supplied,
                 a deck with share >= 3%, conversion <= 1.02 and a 48-52% win
                 rate is a "Cascade". When omitted the four original statuses
                 are returned exactly as before.
    """
    if meta_share >= _HIGH_SHARE and win_rate >= _HIGH_WR:
        return "Pillar", "#3cb44b"       # green
    if meta_share >= _HIGH_SHARE and win_rate < _LOW_WR:
        return "Trap", "#e6194b"         # red
    if meta_share < _LOW_SHARE and win_rate >= _HIGH_WR:
        return "Underplayed", "#f0c040"  # gold
    if (conversion is not None
            and meta_share >= _CASCADE_SHARE
            and conversion <= _CASCADE_CONVERSION
            and _CASCADE_WR[0] <= win_rate <= _CASCADE_WR[1]):
        return "Cascade", CASCADE_COLOR  # orange
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
                    real_wrs: dict | None = None,
                    conversions: dict | None = None) -> list[dict]:
    """Enrich a standings list with prep priority and status.

    Parameters
    ----------
    standings   : list of dicts from get_meta_standings()
    real_wrs    : optional dict {archetype: {win_rate, wins, losses, ...}}
                  from get_real_archetype_winrates()
    conversions : optional dict {archetype: {conversion, ...}} from
                  analysis.conversion.conversion_by_archetype(). Enables the
                  "Cascade" status; without it behaviour is unchanged.

    Returns the same list, each dict gaining:
        prep_priority  : float 0-100
        status         : str   (Pillar / Trap / Underplayed / Fringe / Cascade)
        status_color   : str   hex color
        conversion     : float | None  (only when conversions supplied)
    """
    total_apps = sum(s["appearances"] for s in standings) or 1

    for s in standings:
        share = s["appearances"] / total_apps

        # Prefer real match win rate, fall back to estimated
        real = (real_wrs or {}).get(s["archetype"])
        wr = real["win_rate"] if real else (s.get("est_match_winpct") or 0.5)

        conv = None
        if conversions is not None:
            conv = (conversions.get(s["archetype"]) or {}).get("conversion")
            s["conversion"] = conv

        s["prep_priority"] = prep_priority(share, wr)
        s["status"], s["status_color"] = classify_status(share, wr, conversion=conv)

    return standings
