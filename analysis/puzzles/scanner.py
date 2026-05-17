"""Replay corpus scanner — finds puzzle-worthy turns.

Per-category heuristic functions identify candidate turns based on
text-action patterns in the cached transcript JSON. The orchestrator
walks all replays in data/match_replays/*.json and emits Candidate dicts
that get persisted to the puzzle_inbox table via db.puzzles.

This module is intentionally pure — no DB writes, no GUI. The caller
(scripts/scan_for_puzzles.py) saves results.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = ROOT / "data" / "match_replays"


@dataclass
class Candidate:
    """One puzzle-worthy turn extracted from a replay."""
    arena_match_id: str
    game_num: int
    turn_num: int
    category: str           # 'find_lethal' | 'stabilize' | 'tempo'
    heuristic_score: float  # [0.0, 1.0], for ranking
    evidence: str           # short human-readable why-flagged note

    def to_dict(self) -> dict:
        return asdict(self)


# Regex pattern bank — reused by individual heuristics
_LIFE_RE = re.compile(r"(opp|you)\s+life[:\s]+(-?\d+)", re.IGNORECASE)
_YOU_CAST_RE = re.compile(r"^You cast\s+(.+?)(\s+→|\s+\(|$)", re.IGNORECASE)


def _parse_life_from_actions(actions: list[str]) -> tuple[Optional[int], Optional[int]]:
    """Return (your_life, opp_life) parsed from a turn's actions list,
    or (None, None) if neither was logged that turn."""
    you = opp = None
    for a in actions or []:
        m = _LIFE_RE.search(a or "")
        if not m:
            continue
        who, val = m.group(1).lower(), int(m.group(2))
        if who == "you":
            you = val
        elif who == "opp":
            opp = val
    return you, opp


def scan_match(arena_match_id: str, transcript: dict) -> list[Candidate]:
    """Run all 3 category heuristics on one match transcript. Returns
    Candidate list (may be empty). Pure — no I/O."""
    candidates: list[Candidate] = []
    games = transcript.get("games") or []
    for g in games:
        game_num = int(g.get("game_num", 1))
        turns = g.get("turns") or []
        # Each heuristic returns its own candidates for this game
        candidates.extend(_scan_find_lethal(arena_match_id, game_num, turns))
        candidates.extend(_scan_stabilize(arena_match_id, game_num, turns))
        candidates.extend(_scan_tempo(arena_match_id, game_num, turns))
    return candidates


# ── Stub heuristics — filled in by later tasks ────────────────────

def _scan_find_lethal(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    """Find lethal heuristic: turn N where you cast >= 3 noncreature
    spells AND opp life went from >= 8 down to 0 in that turn.

    Score: 0.6 * (spells_cast / 5) + 0.4 * (1 - opp_final_life / starting_life)
    (per spec; first-pass formula, tunes after real data lands)."""
    out: list[Candidate] = []
    for t in turns:
        actions = t.get("actions") or []
        spells_cast = sum(
            1 for a in actions if _YOU_CAST_RE.search(a or "")
        )
        if spells_cast < 3:
            continue
        # Capture opp life trajectory across this turn
        opp_lives: list[int] = []
        for a in actions:
            m = _LIFE_RE.search(a or "")
            if m and m.group(1).lower() == "opp":
                opp_lives.append(int(m.group(2)))
        if not opp_lives:
            continue
        starting = max(opp_lives)
        final = min(opp_lives)
        if starting < 8 or final > 0:
            continue
        # Score
        spell_term = min(1.0, spells_cast / 5.0) * 0.6
        life_term = (1.0 - final / max(starting, 1)) * 0.4
        score = round(spell_term + life_term, 3)
        out.append(Candidate(
            arena_match_id=match_id,
            game_num=game_num,
            turn_num=int(t.get("turn", 0)),
            category="find_lethal",
            heuristic_score=score,
            evidence=f"{spells_cast} spells, opp {starting}→{final}",
        ))
    return out


def _scan_stabilize(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    return []


def _scan_tempo(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    return []
