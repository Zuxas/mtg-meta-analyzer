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
    opponent_archetype: str = None,
    limit: int = 20,
) -> List[dict]:
    """
    Return Bo3 sideboard plans extracted from Untapped replays whose
    color identity matches the given archetype, optionally filtered by
    opponent matchup.

    Each plan represents a real game-to-game transition (diff of decklists
    between game 1->2 or 2->3) from a Mythic-level Bo3 match.

    Match strategy: archetype name -> color string (e.g. 'Azorius Control'
    -> 'WU'), then filter SB plans by colors_str. Returns empty list if
    archetype color can't be derived.

    When opponent_archetype is provided, filter to plans where the
    opponent's classified archetype matches (case-insensitive, substring
    match -- so "Selesnya Landfall" matches "Selesnya" and vice versa).

    Each result dict has:
        deck_name, player_name, from_game, to_game, n_cards_swapped,
        cards_in: [{name, count}, ...], cards_out: [{name, count}, ...],
        opponent_archetype: str (classified from replay log)
    """
    colors = archetype_colors(archetype)
    if not colors:
        return []

    # Two-pass filter: first try the classified friendly_archetype column
    # (substring match either direction). If we get plans, use those -- they're
    # the most specific signal. Otherwise fall back to color-only matching,
    # preserving backward-compatible behavior for archetypes whose plans
    # haven't been classified yet (or whose classified value disagrees).
    base_sql = """
        SELECT
            v.deck_name, v.player_name,
            v.from_game, v.to_game,
            v.n_cards_swapped,
            v.cards_in_json, v.cards_out_json,
            v.colors_str,
            r.match_timestamp,
            p.opponent_archetype,
            p.friendly_archetype
        FROM v_untapped_sideboard_plans_with_meta v
        LEFT JOIN untapped_replays r ON v.replay_short_id = r.short_id
        LEFT JOIN untapped_sideboard_plans p ON p.id = v.id
    """

    def _run(sql: str, params: list):
        with sqlite3.connect(str(DB_PATH)) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchall()

    def _opp_clause():
        if opponent_archetype:
            return (
                " AND (lower(p.opponent_archetype) LIKE ? "
                "OR ? LIKE '%' || lower(p.opponent_archetype) || '%')",
                [f"%{opponent_archetype.lower()}%", opponent_archetype.lower()],
            )
        return "", []

    # Pass 1: classified friendly_archetype substring match
    arch_lower = archetype.lower()
    where1 = (
        " WHERE (lower(p.friendly_archetype) LIKE ? "
        "OR ? LIKE '%' || lower(p.friendly_archetype) || '%') "
        "AND COALESCE(p.friendly_archetype, '') NOT IN ('', 'Unknown')"
    )
    params1 = [f"%{arch_lower}%", arch_lower]
    opp_sql, opp_params = _opp_clause()
    sql1 = base_sql + where1 + opp_sql + " ORDER BY COALESCE(r.match_timestamp, '') DESC LIMIT ?"
    rows = _run(sql1, params1 + opp_params + [limit])

    # Pass 2 (fallback): color-only matching
    if not rows:
        opp_sql, opp_params = _opp_clause()
        sql2 = (base_sql + " WHERE v.colors_str = ?" + opp_sql +
                " ORDER BY COALESCE(r.match_timestamp, '') DESC LIMIT ?")
        rows = _run(sql2, [colors] + opp_params + [limit])

    sql = None  # legacy var to satisfy old code path below; not used
    params = None

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
            "opponent_archetype": (r["opponent_archetype"] if "opponent_archetype" in r.keys() else "") or "",
            "friendly_archetype": (r["friendly_archetype"] if "friendly_archetype" in r.keys() else "") or "",
        })
    return out


def get_mythic_card_inclusion(archetype: str) -> dict:
    """For each card seen in mythic-tier replays of this archetype, return
    inclusion rate + avg quantity.

    Returns: {card_name: {"inclusion_rate": 0..1, "n_decks": int,
                          "total_decks": int, "avg_qty": float}}

    Substring-matches archetype name in untapped_replay_decks.archetype
    (so 'Izzet Prowess' matches 'Izzet Prowess' but you'd need exact
    name -- no fuzzy matching across e.g. 'Mono Green' vs 'Mono-Green').
    """
    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        total_row = con.execute("""
            SELECT COUNT(DISTINCT replay_short_id) AS n FROM untapped_replay_decks
            WHERE lower(archetype) = lower(?)
        """, (archetype,)).fetchone()
        total = total_row["n"] if total_row else 0
        if total == 0:
            return {}

        rows = con.execute("""
            SELECT card_name,
                   COUNT(DISTINCT replay_short_id) AS n_decks,
                   ROUND(AVG(CAST(quantity AS REAL)), 2) AS avg_qty
            FROM untapped_replay_decks
            WHERE lower(archetype) = lower(?)
            GROUP BY card_name
            ORDER BY n_decks DESC, card_name
        """, (archetype,)).fetchall()

    out = {}
    for r in rows:
        out[r["card_name"]] = {
            "inclusion_rate": r["n_decks"] / total if total else 0.0,
            "n_decks":        r["n_decks"],
            "total_decks":    total,
            "avg_qty":        r["avg_qty"],
        }
    return out


def get_known_sb_opponents(archetype: str) -> List[str]:
    """Return distinct opponent archetypes that exist in SB plans for the
    given (color-matched) archetype, sorted by frequency. Used to populate
    a 'filter by matchup' dropdown in the archetype-detail SB plans tab."""
    colors = archetype_colors(archetype)
    if not colors:
        return []

    with sqlite3.connect(str(DB_PATH)) as con:
        rows = con.execute("""
            SELECT p.opponent_archetype, COUNT(*) as n
            FROM untapped_sideboard_plans p
            JOIN v_untapped_sideboard_plans_with_meta v ON v.id = p.id
            WHERE v.colors_str = ?
              AND COALESCE(p.opponent_archetype, '') != ''
              AND COALESCE(p.opponent_archetype, '') != 'Unknown'
              AND p.n_cards_swapped > 0
            GROUP BY p.opponent_archetype
            ORDER BY n DESC
        """, (colors,)).fetchall()
    return [r[0] for r in rows]


# Skill-curve format mapping — Untapped only reports per-tier WR for Bo1
# meta data ("Ladder", "Explorer_Ladder", etc.).  Bo3 ("Traditional_*")
# rows have NULL win_rate at all tiers.
_SKILL_CURVE_FORMAT_MAP = {
    "standard": "Ladder",
    "pioneer":  "Explorer_Ladder",
    "historic": "Historic_Ladder",
    "timeless": "Timeless_Ladder",
    "alchemy":  "Alchemy_Ladder",
}


def get_skill_curve(
    format_name: str,
    min_plat_matches: int = 100,
    limit: int = 50,
) -> List[dict]:
    """
    Per-archetype Bo1 ladder skill curve: WR by rank tier
    (bronze/silver/gold/platinum) and the bronze->plat WR delta.

    Positive climb_delta_wr means the archetype scales with skill
    (better players win more with it); negative means it's a
    "low-skill trap" that drops off as opponents improve.

    Returns rows sorted by climb_delta_wr DESC. Filters to archetypes
    with at least `min_plat_matches` matches at Platinum tier.
    """
    event_name = _SKILL_CURVE_FORMAT_MAP.get(format_name.lower())
    if not event_name:
        return []

    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT archetype_name, colors_str,
                   bronze_wr, silver_wr, gold_wr, plat_wr,
                   bronze_matches, plat_matches,
                   climb_delta_wr
            FROM v_untapped_meta_skill_curve
            WHERE format = ?
              AND last_7_days = 0
              AND bronze_wr IS NOT NULL
              AND plat_wr   IS NOT NULL
              AND plat_matches >= ?
            ORDER BY climb_delta_wr DESC
            LIMIT ?
        """, (event_name, min_plat_matches, limit)).fetchall()

    return [dict(r) for r in rows]


def get_bo3_tier_wrs(format_name: str = "standard") -> dict:
    """Per-archetype Bo3 WR aggregated across opponents at each high tier.

    Pulls from v_untapped_premium_matchups_named (premium endpoint, has
    Diamond + Mythic that the Bo1 meta endpoint lacks). Aggregates by
    summing observed_match_count + matches_won across all opponents at
    each rank tier.

    Returns: {archetype_name: {"plat_wr": float|None,
                              "diamond_wr": float|None,
                              "mythic_wr": float|None,
                              "plat_matches": int,
                              "diamond_matches": int,
                              "mythic_matches": int}}
    """
    event_name = _FORMAT_MAP.get(format_name.lower())
    if not event_name:
        return {}

    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT m.friendly_archetype AS arch, m.rank_tier AS tier,
                   SUM(m.observed_match_count) AS matches,
                   SUM(m.matches_won) AS wins
            FROM v_untapped_premium_matchups_named m
            WHERE m.format = ? AND m.last_7_days = 0
              AND m.friendly_archetype IS NOT NULL
              AND m.rank_tier IN ('Platinum', 'Diamond', 'Mythic')
            GROUP BY m.friendly_archetype, m.rank_tier
        """, (event_name,)).fetchall()

    out: dict = {}
    for r in rows:
        arch = r["arch"]
        tier = r["tier"]
        n = int(r["matches"] or 0)
        w = float(r["wins"] or 0.0)
        if arch not in out:
            out[arch] = {
                "plat_wr": None, "diamond_wr": None, "mythic_wr": None,
                "plat_matches": 0, "diamond_matches": 0, "mythic_matches": 0,
            }
        if n > 0:
            wr = w / n
            if tier == "Platinum":
                out[arch]["plat_wr"] = round(wr * 100, 2)
                out[arch]["plat_matches"] = n
            elif tier == "Diamond":
                out[arch]["diamond_wr"] = round(wr * 100, 2)
                out[arch]["diamond_matches"] = n
            elif tier == "Mythic":
                out[arch]["mythic_wr"] = round(wr * 100, 2)
                out[arch]["mythic_matches"] = n
    return out


def get_mythic_leaderboard(limit: int = 30, format_name: str = "standard") -> List[dict]:
    """
    Top-N entries from the latest Bo3 mythic ladder snapshot for the
    given format, sorted by rank_approx ASC (top ranks first).

    Filtered to Bo3 only ('Traditional_*') -- Bo1 mythic entries are
    excluded. Cross-format entries are excluded too.

    Each row has:
        player_name, archetype_primary (color combo), colors_str,
        matches_count, win_rate, rank_approx
    """
    event_name = _FORMAT_MAP.get(format_name.lower())
    if not event_name:
        return []
    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT e.player_name, e.archetype_primary, e.colors_str,
                   e.matches_count, e.win_rate, e.rank_approx
            FROM untapped_entries e
            JOIN untapped_meta_periods mp ON mp.id = e.meta_period_id
            JOIN untapped_snapshots s ON s.id = e.snapshot_id
            WHERE e.rank_approx IS NOT NULL
              AND mp.event_name = ?
              AND s.id = (SELECT MAX(id) FROM untapped_snapshots)
            ORDER BY e.rank_approx ASC
            LIMIT ?
        """, (event_name, limit)).fetchall()
    return [dict(r) for r in rows]


def get_mythic_archetype_rollup(limit: int = 12, format_name: str = "standard") -> List[dict]:
    """
    Aggregated archetype data from the latest Bo3 mythic snapshot for
    the given format: archetype, colors, n_players, total_matches,
    weighted_wr, as_of_utc. Sorted by n_players DESC.

    Filtered to Bo3 only ('Traditional_*'). Bo1 entries excluded.
    """
    event_name = _FORMAT_MAP.get(format_name.lower())
    if not event_name:
        return []
    with sqlite3.connect(str(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""
            SELECT e.archetype_primary AS archetype,
                   e.colors_str AS colors,
                   COUNT(*) AS n_players,
                   SUM(e.matches_count) AS total_matches,
                   ROUND(SUM(e.matches_count * e.win_rate)
                         / NULLIF(SUM(e.matches_count), 0), 2) AS weighted_wr,
                   MAX(s.captured_at_utc) AS as_of_utc
            FROM untapped_entries e
            JOIN untapped_meta_periods mp ON mp.id = e.meta_period_id
            JOIN untapped_snapshots s ON s.id = e.snapshot_id
            WHERE mp.event_name = ?
              AND s.id = (SELECT MAX(id) FROM untapped_snapshots)
            GROUP BY e.archetype_primary, e.colors_str
            ORDER BY n_players DESC
            LIMIT ?
        """, (event_name, limit)).fetchall()
    return [dict(r) for r in rows]
