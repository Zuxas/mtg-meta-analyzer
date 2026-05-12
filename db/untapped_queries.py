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
import json
import sqlite3
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mtg_meta.db"

# Archetype-name prefix -> color identity (longest match wins).
# Ordered roughly by specificity so longer names match before shorter ones.
_COLOR_NAMES = [
    # 5-color
    ("five-color", "WUBRG"), ("5-color", "WUBRG"), ("5c", "WUBRG"),
    ("domain", "WUBRG"),
    # 4-color
    ("yore", "WUBR"), ("glint", "UBRG"), ("dune", "WBRG"), ("ink", "WURG"),
    ("witch", "WUBG"),
    # 3-color (shards + wedges)
    ("bant", "WUG"), ("esper", "WUB"), ("grixis", "UBR"), ("jund", "BRG"),
    ("naya", "WRG"), ("abzan", "WBG"), ("jeskai", "WUR"), ("sultai", "UBG"),
    ("mardu", "WBR"), ("temur", "URG"),
    # 2-color
    ("azorius", "WU"), ("dimir", "UB"), ("rakdos", "BR"), ("gruul", "RG"),
    ("selesnya", "WG"), ("orzhov", "WB"), ("izzet", "UR"), ("golgari", "BG"),
    ("boros", "WR"), ("simic", "UG"),
    # Mono
    ("mono white", "W"), ("mono-white", "W"),
    ("mono blue", "U"),  ("mono-blue", "U"),
    ("mono black", "B"), ("mono-black", "B"),
    ("mono red", "R"),   ("mono-red", "R"),
    ("mono green", "G"), ("mono-green", "G"),
]


def archetype_colors(archetype: str) -> str:
    """Return the canonical color string ('WU', 'WUBRG', etc.) for an
    archetype name, or '' if it can't be derived. Case-insensitive.

    Scans the whole name for the longest color-tag match so format
    prefixes ('Modern Boros Energy') or trailing tags ('UR Prowess') still
    resolve. Mono-color variants take priority when present."""
    if not archetype:
        return ""
    lo = archetype.lower()
    best = ""
    for tag, colors in _COLOR_NAMES:
        if tag in lo and len(tag) > len(best):
            best = tag
            best_colors = colors
    return best_colors if best else ""

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


def get_sideboard_plans_for_archetype(
    archetype: str,
    limit: int = 20,
) -> List[dict]:
    """
    Return Bo3 sideboard plans extracted from Untapped replays whose
    color identity matches the given archetype.

    Each plan represents a real game-to-game transition (diff of decklists
    between game 1->2 or 2->3) from a Mythic-level Bo3 match.

    Match strategy: archetype name -> color string (e.g. 'Azorius Control'
    -> 'WU'), then filter SB plans by colors_str. Returns empty list if
    archetype color can't be derived.

    Each result dict has:
        deck_name, player_name, from_game, to_game, n_cards_swapped,
        cards_in: [{name, count}, ...], cards_out: [{name, count}, ...]
    """
    colors = archetype_colors(archetype)
    if not colors:
        return []

    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT
                v.deck_name, v.player_name,
                v.from_game, v.to_game,
                v.n_cards_swapped,
                v.cards_in_json, v.cards_out_json,
                v.colors_str,
                r.match_timestamp
            FROM v_untapped_sideboard_plans_with_meta v
            LEFT JOIN untapped_replays r ON v.replay_short_id = r.short_id
            WHERE v.colors_str = ?
            ORDER BY COALESCE(r.match_timestamp, '') DESC
            LIMIT ?
        """, (colors, limit)).fetchall()

    out: List[dict] = []
    for r in rows:
        try:
            cards_in = json.loads(r["cards_in_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            cards_in = []
        try:
            cards_out = json.loads(r["cards_out_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            cards_out = []
        out.append({
            "deck_name":       r["deck_name"] or "(unnamed)",
            "player_name":     r["player_name"] or "(unknown)",
            "from_game":       r["from_game"],
            "to_game":         r["to_game"],
            "n_cards_swapped": r["n_cards_swapped"],
            "cards_in":        cards_in,
            "cards_out":       cards_out,
            "colors_str":      r["colors_str"],
            "match_timestamp": r["match_timestamp"],
        })
    return out
