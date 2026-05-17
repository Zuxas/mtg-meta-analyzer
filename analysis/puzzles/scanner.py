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
    """Stabilize heuristic: turn N where your life <= 5 AND match
    continued past N AND you eventually won the match.

    Score: 0.5 * (1 - your_life_at_turn / 20) + 0.5 * (did_win ? 1.0 : 0.5)
    """
    if not turns:
        return []
    # Determine if user eventually won this game (opp life hit 0 last)
    did_win = False
    for t in turns:
        for a in t.get("actions") or []:
            m = _LIFE_RE.search(a or "")
            if m and m.group(1).lower() == "opp" and int(m.group(2)) <= 0:
                did_win = True
                break
        if did_win:
            break

    out: list[Candidate] = []
    for idx, t in enumerate(turns):
        your_life, _ = _parse_life_from_actions(t.get("actions") or [])
        if your_life is None or your_life > 5:
            continue
        # Match must continue past this turn — i.e. there's at least one
        # later turn AND user didn't die during this turn.
        if your_life <= 0:
            continue
        if idx >= len(turns) - 1:
            continue
        if not did_win:
            continue
        win_term = 1.0
        life_term = 1.0 - (max(your_life, 0) / 20.0)
        score = round(0.5 * life_term + 0.5 * win_term, 3)
        out.append(Candidate(
            arena_match_id=match_id,
            game_num=game_num,
            turn_num=int(t.get("turn", 0)),
            category="stabilize",
            heuristic_score=score,
            evidence=f"your life {your_life}, won={did_win}",
        ))
    return out


def _scan_tempo(
    match_id: str, game_num: int, turns: list[dict]
) -> list[Candidate]:
    """Simplified Phase 2 tempo heuristic: turn N (your turn) where
    you cast >= 2 INSTANT-typed cards. Instant-speed cards used at
    sorcery speed often represent missed tempo (could have held them
    for opp's turn for more info).

    Score: 0.5 * (instants_cast / 3) + 0.5 (constant for "interesting"
    until we have richer data to differentiate)."""
    out: list[Candidate] = []
    for t in turns:
        if int(t.get("active_seat", 0)) != 1:
            continue  # only your turns
        actions = t.get("actions") or []
        instant_names: list[str] = []
        for a in actions:
            m = _YOU_CAST_RE.search(a or "")
            if not m:
                continue
            name = m.group(1).strip()
            if _is_instant_card(name):
                instant_names.append(name)
        if len(instant_names) < 2:
            continue
        score = round(
            0.5 * min(1.0, len(instant_names) / 3.0) + 0.5, 3
        )
        out.append(Candidate(
            arena_match_id=match_id,
            game_num=game_num,
            turn_num=int(t.get("turn", 0)),
            category="tempo",
            heuristic_score=score,
            evidence=f"{len(instant_names)} instants on own turn: "
                     + ", ".join(instant_names[:3]),
        ))
    return out


def _is_instant_card(card_name: str) -> bool:
    """Cheap card_data lookup for the 'is this an Instant?' check.

    Returns False on lookup miss — don't flag cards we can't identify
    (avoids false positives for fabricated / token / split-card names)."""
    try:
        from db.database import get_connection
        with get_connection() as c:
            row = c.execute(
                "SELECT type_line FROM card_data WHERE name = ?",
                (card_name,),
            ).fetchone()
        if row is None:
            return False
        return "instant" in (row["type_line"] or "").lower()
    except Exception:
        return False


def scan_all() -> list[Candidate]:
    """Walk every transcript in CACHE_DIR and aggregate Candidates."""
    if not CACHE_DIR.exists():
        return []
    out: list[Candidate] = []
    for path in sorted(CACHE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        match_id = path.stem  # filename minus .json
        out.extend(scan_match(match_id, data))
    return out
