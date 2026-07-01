"""Compare actual in-game sideboard plans against canonical plans.

For each match_log row that has both a my_deck_id AND a stored SB plan
(in match_log_sb_plans), look up the canonical plan in saved_sb_plans
(deck_id + opponent_archetype) and compute the diff:

  - cards_followed: cards in BOTH canonical and actual (right call)
  - cards_missing : in canonical but not actual (you skipped sideboarding
                    something the plan said to bring in)
  - cards_unplanned: in actual but not canonical (you brought in cards
                    not on the documented plan -- could be adaptation
                    or a mistake)

Public API:
    compare_match_to_canonical(match_log_id) -> dict | None
        {
          'canonical_plan_id', 'opp_archetype', 'difficulty',
          'transitions': [
            {
              'from_game', 'to_game',
              'canonical_in': {name: qty}, 'canonical_out': {name: qty},
              'actual_in':    {name: qty}, 'actual_out':    {name: qty},
              'in_followed', 'in_missing', 'in_unplanned',
              'out_followed', 'out_missing', 'out_unplanned',
              'in_match_pct', 'out_match_pct',
            }, ...
          ],
        }
        Returns None if no canonical plan exists for this matchup.
"""
from __future__ import annotations

import json
from typing import Optional

from db.database import get_connection


def _normalize_archetype(s: str) -> str:
    """Normalize for fuzzy matching: lowercase, strip parens, strip whitespace."""
    if not s:
        return ""
    s = s.lower().strip()
    # Strip parenthesized suffixes like "(Stormchaser)" or "(no Stormchaser)"
    if "(" in s:
        s = s.split("(")[0].strip()
    return s


# Guild name <-> color-code equivalence (2026-05-16 chain S2, landed 2026-07-01).
# "Azorius Control" should match a plan saved as "UW Control" and vice versa.
_GUILD_COLORS = {
    "azorius": "uw", "dimir": "ub", "rakdos": "br", "gruul": "rg",
    "selesnya": "wg", "orzhov": "wb", "izzet": "ur", "golgari": "bg",
    "boros": "wr", "simic": "ug",
}
_WUBRG_ORDER = {c: i for i, c in enumerate("wubrg")}


def _first_token_key(token: str) -> str:
    """Canonical key for an archetype's first token so that guild names and
    color codes compare equal in either direction:
      azorius -> 'uw', uw -> 'uw', wu -> 'uw', boros -> 'rw', wr -> 'rw'.
    Color pairs/triples are sorted in WUBRG order; anything else passes through."""
    token = token.lower()
    if token in _GUILD_COLORS:
        token = _GUILD_COLORS[token]
    if 2 <= len(token) <= 3 and all(ch in _WUBRG_ORDER for ch in token):
        return "".join(sorted(token, key=_WUBRG_ORDER.get))
    return token


def _guild_variants(norm: str) -> set:
    """All normalized spellings of an archetype name obtained by swapping its
    first token between guild-name and color-code form. Includes the original."""
    variants = {norm}
    parts = norm.split()
    if not parts:
        return variants
    first, rest = parts[0], parts[1:]
    key = _first_token_key(first)
    if key != first:
        variants.add(" ".join([key] + rest))
    # color-code -> guild name (reverse direction)
    for guild, colors in _GUILD_COLORS.items():
        if key == _first_token_key(colors):
            variants.add(" ".join([guild] + rest))
    return variants


def _find_canonical_plan(conn, deck_id: int, opp_archetype: str) -> Optional[dict]:
    """Look up the canonical SB plan in saved_sb_plans.

    Tries exact match first, then case-insensitive normalized match
    against either the full opp_archetype or its first word(s)."""
    if not opp_archetype:
        return None
    rows = conn.execute(
        "SELECT id, opponent_archetype, play_in, play_out, "
        "       draw_in, draw_out, difficulty "
        "FROM saved_sb_plans WHERE deck_id = ?",
        (deck_id,),
    ).fetchall()
    target_norm = _normalize_archetype(opp_archetype)
    if not target_norm:
        return None

    # Exact (case-insensitive) match first
    for r in rows:
        if (r["opponent_archetype"] or "").strip().lower() == opp_archetype.lower():
            return dict(r)

    # Normalized match (drop parenthetical suffix)
    for r in rows:
        if _normalize_archetype(r["opponent_archetype"]) == target_norm:
            return dict(r)

    # Guild <-> color-code match, both directions (before first-word fallback):
    # "Azorius Control" == "UW Control", "WR Aggro" == "Boros Aggro", etc.
    target_variants = _guild_variants(target_norm)
    for r in rows:
        plan_variants = _guild_variants(_normalize_archetype(r["opponent_archetype"]))
        if target_variants & plan_variants:
            return dict(r)

    # Token-prefix match: opp "Selesnya Aggro" matches plan
    # "Selesnya Landfall" if "selesnya" is the first word.
    # Compare through _first_token_key so guild/color spellings agree.
    target_first = target_norm.split()[0] if target_norm else ""
    if target_first:
        target_key = _first_token_key(target_first)
        for r in rows:
            plan_norm = _normalize_archetype(r["opponent_archetype"])
            plan_first = plan_norm.split()[0] if plan_norm else ""
            if (target_key == _first_token_key(plan_first)
                    and target_first not in ("u", "w", "b", "r", "g")):
                return dict(r)

    return None


def _diff_card_lists(canonical: dict, actual: dict) -> dict:
    """Compute followed / missing / unplanned card maps.

    All inputs are {name: qty} dicts. Returns:
      followed:  {name: min(c, a)}  -- counts of cards in BOTH
      missing:   {name: c - a}      -- counts in canonical but not actual
      unplanned: {name: a - c}      -- counts in actual but not canonical
    """
    canonical = canonical or {}
    actual = actual or {}
    followed = {}
    missing = {}
    unplanned = {}
    all_names = set(canonical) | set(actual)
    for name in all_names:
        c = canonical.get(name, 0)
        a = actual.get(name, 0)
        f = min(c, a)
        if f:
            followed[name] = f
        if c > a:
            missing[name] = c - a
        elif a > c:
            unplanned[name] = a - c
    return {"followed": followed, "missing": missing, "unplanned": unplanned}


def compare_match_to_canonical(match_log_id: int) -> Optional[dict]:
    """Compare the per-game SB plans of a match against the canonical
    plan stored in saved_sb_plans. Returns None if no canonical plan
    exists for this (deck, opp_archetype) pair."""
    with get_connection() as conn:
        match_row = conn.execute(
            "SELECT id, my_deck_id, opp_deck FROM match_log WHERE id = ?",
            (match_log_id,),
        ).fetchone()
        if match_row is None:
            return None
        my_deck_id = match_row["my_deck_id"]
        opp = match_row["opp_deck"] or ""
        if my_deck_id is None or not opp:
            return None

        canonical = _find_canonical_plan(conn, my_deck_id, opp)
        if canonical is None:
            return None

        sb_rows = conn.execute(
            "SELECT from_game, to_game, cards_in_json, cards_out_json "
            "FROM match_log_sb_plans WHERE match_log_id = ? "
            "ORDER BY from_game",
            (match_log_id,),
        ).fetchall()

    # saved_sb_plans stores card NAME lists (each may be repeated for qty).
    # Convert to {name: qty} via Counter.
    from collections import Counter
    canonical_in = dict(Counter(json.loads(canonical["play_in"] or "[]")))
    canonical_out = dict(Counter(json.loads(canonical["play_out"] or "[]")))
    # Note: there's also draw_in/draw_out for on-the-draw plans. We use
    # play_in/out as the primary; future enhancement could split by P/D.

    transitions = []
    for r in sb_rows:
        actual_in = json.loads(r["cards_in_json"] or "{}")
        actual_out = json.loads(r["cards_out_json"] or "{}")
        in_diff = _diff_card_lists(canonical_in, actual_in)
        out_diff = _diff_card_lists(canonical_out, actual_out)
        canonical_in_total = sum(canonical_in.values())
        canonical_out_total = sum(canonical_out.values())
        in_match_pct = (
            (sum(in_diff["followed"].values()) / canonical_in_total * 100)
            if canonical_in_total else 0
        )
        out_match_pct = (
            (sum(out_diff["followed"].values()) / canonical_out_total * 100)
            if canonical_out_total else 0
        )
        transitions.append({
            "from_game": r["from_game"],
            "to_game": r["to_game"],
            "canonical_in": canonical_in,
            "canonical_out": canonical_out,
            "actual_in": actual_in,
            "actual_out": actual_out,
            "in_followed": in_diff["followed"],
            "in_missing": in_diff["missing"],
            "in_unplanned": in_diff["unplanned"],
            "out_followed": out_diff["followed"],
            "out_missing": out_diff["missing"],
            "out_unplanned": out_diff["unplanned"],
            "in_match_pct": in_match_pct,
            "out_match_pct": out_match_pct,
        })

    return {
        "canonical_plan_id": canonical["id"],
        "canonical_archetype": canonical["opponent_archetype"],
        "difficulty": canonical["difficulty"],
        "transitions": transitions,
    }
