"""
db/untapped_queries.py -- Untapped.gg query helpers

Surfaces MTGA-ladder Bo3 matchup data from untapped_* tables into the same
dict shape used by db.matchup_queries.get_matchup_matrix(). Aggregates
across rank tiers weighted by observed match count.

Bo1 data (v_untapped_matchups_named, showcase endpoint) is deliberately
NOT used here -- merging Bo1 ladder into a Bo3 paper-matchup matrix would
quietly mislead tournament prep. v_untapped_premium_matchups_named is
filtered to the Bo3 'Traditional_*' formats below.
"""

from pathlib import Path
import sqlite3
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mtg_meta.db"

# Map mtg-meta-analyzer format names -> Untapped event_name (Bo3 only).
# Modern / Legacy / Pauper are not on MTGA; return {} for those.
_FORMAT_MAP = {
    "standard": "Traditional_Ladder",
    "pioneer":  "Traditional_Explorer_Ladder",
    "historic": "Traditional_Historic_Ladder",
    "timeless": "Traditional_Timeless_Ladder",
    "alchemy":  "Traditional_Alchemy_Ladder",
}


def get_untapped_matchup_matrix(
    format_name: str,
    last_7_days: bool = False,
) -> Dict[str, Dict[str, dict]]:
    """
    Build a matchup matrix from Untapped premium Bo3 data.

    Aggregates across all rank tiers (Silver..Mythic) weighted by
    observed_match_count.  Same shape as get_matchup_matrix():

        { friendly_arch: { opponent_arch: {"winrate": 0..1, "matches": N} } }

    Unsupported formats return {} silently.
    """
    from analysis.archetypes import normalize as _norm_arch

    event_name = _FORMAT_MAP.get(format_name.lower())
    if not event_name:
        return {}

    aggregator: dict = {}  # (a, b) -> [wins_sum, matches_sum]

    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT friendly_archetype, opponent_archetype,
                   observed_match_count, matches_won
            FROM v_untapped_premium_matchups_named
            WHERE format = ?
              AND last_7_days = ?
              AND friendly_archetype IS NOT NULL
              AND opponent_archetype IS NOT NULL
        """, (event_name, 1 if last_7_days else 0)).fetchall()

    for r in rows:
        a = _norm_arch(r["friendly_archetype"])
        b = _norm_arch(r["opponent_archetype"])
        n = int(r["observed_match_count"] or 0)
        w = float(r["matches_won"] or 0.0)
        if n <= 0:
            continue
        acc = aggregator.setdefault((a, b), [0.0, 0])
        acc[0] += w
        acc[1] += n

    matrix: dict = {}
    for (a, b), (wins, n) in aggregator.items():
        if n <= 0:
            continue
        matrix.setdefault(a, {})[b] = {
            "winrate": round(wins / n, 4),
            "matches": n,
        }

    return matrix
