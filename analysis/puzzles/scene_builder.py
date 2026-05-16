"""Scene reconstruction for puzzle scenarios.

Given an (arena_match_id, game_num, turn_num), rebuilds the full board state
from the cached replay transcript. Returns a Scene dataclass that the puzzle
widget can render and that gets serialized into puzzles.scene_json.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal, Optional

# Same cache dir the Watch Replay viewer writes to
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "match_replays"


@dataclass
class CardInZone:
    name: str
    grpid: Optional[int] = None
    scryfall_image_url: Optional[str] = None
    tapped: bool = False
    power: Optional[int] = None
    toughness: Optional[int] = None
    counters: dict[str, int] = field(default_factory=dict)
    is_face_down: bool = False


@dataclass
class PlayerState:
    name: str
    archetype: str = "?"
    life: int = 20
    hand: list[CardInZone] = field(default_factory=list)
    battlefield_lands: list[CardInZone] = field(default_factory=list)
    battlefield_creatures: list[CardInZone] = field(default_factory=list)
    battlefield_other: list[CardInZone] = field(default_factory=list)
    graveyard_count: int = 0
    library_count: int = 60
    mana_available: dict[str, int] = field(default_factory=dict)


@dataclass
class Scene:
    arena_match_id: str
    game_num: int
    turn_num: int
    play_or_draw: Literal["play", "draw"]
    you: PlayerState
    opp: PlayerState
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        you = _player_from_dict(d["you"])
        opp = _player_from_dict(d["opp"])
        return cls(
            arena_match_id=d["arena_match_id"],
            game_num=d["game_num"],
            turn_num=d["turn_num"],
            play_or_draw=d["play_or_draw"],
            you=you, opp=opp,
            notes=d.get("notes", ""),
        )


def _player_from_dict(d: dict) -> PlayerState:
    def _cards(key):
        return [CardInZone(**c) for c in d.get(key, [])]
    return PlayerState(
        name=d["name"],
        archetype=d.get("archetype", "?"),
        life=d.get("life", 20),
        hand=_cards("hand"),
        battlefield_lands=_cards("battlefield_lands"),
        battlefield_creatures=_cards("battlefield_creatures"),
        battlefield_other=_cards("battlefield_other"),
        graveyard_count=d.get("graveyard_count", 0),
        library_count=d.get("library_count", 60),
        mana_available=d.get("mana_available", {}),
    )


_LIFE_RE = re.compile(r"(opp|you)\s+life[:\s]+(-?\d+)", re.IGNORECASE)


def build_scene(
    arena_match_id: str, game_num: int, turn_num: int
) -> Optional[Scene]:
    """Walk the cached transcript up to turn_num, return a Scene snapshot.

    Phase 1 implementation is intentionally minimal: extracts life totals
    from the transcript's text actions and a hand snapshot from any
    'Opening hand' line in the target game's earliest turn. Battlefield /
    mana / tap state are left empty for Phase 1 — the seeder script will
    let the puzzle author fill those in. Phase 2 will mine the full
    gameStateMessage.zones for an authoritative snapshot.
    """
    path = CACHE_DIR / f"{arena_match_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    games = data.get("games", [])
    game = next((g for g in games if g.get("game_num") == game_num), None)
    if game is None:
        return None

    you = PlayerState(name="You", archetype="?", life=20)
    opp = PlayerState(name="Opp", archetype="?", life=20)

    # Walk turns up to and including turn_num
    for t in game.get("turns", []):
        if t.get("turn", 0) > turn_num:
            break
        for action in t.get("actions", []) or []:
            m = _LIFE_RE.search(action)
            if m:
                who, val = m.group(1).lower(), int(m.group(2))
                if who == "you":
                    you.life = val
                else:
                    opp.life = val
            if action.lower().startswith("opening hand"):
                # "Opening hand (kept on 7): Card A, Card B, ..."
                _, _, rest = action.partition(":")
                names = [n.strip() for n in rest.split(",") if n.strip()]
                you.hand = [CardInZone(name=n) for n in names]

    return Scene(
        arena_match_id=arena_match_id,
        game_num=game_num,
        turn_num=turn_num,
        play_or_draw="draw",  # Phase 1 default; seeder script can override
        you=you,
        opp=opp,
        notes=f"Scene built from {path.name} at T{turn_num}.",
    )
