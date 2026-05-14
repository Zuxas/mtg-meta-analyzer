"""Walk data/untapped/replays/ and write match_log rows.

Sister module to untapped_opponent_classifier (which writes saved_sb_plans).
Same replay corpus, different output table. Both run in the M/W/F pipeline.

Per design 2026-05-13: this is the primary auto-import path for Arena games.
The live-tail MTGA watcher was intentionally NOT built -- Untapped Companion
already does live capture, and we pull the replays down M/W/F.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Iterable, Optional

from db.match_log import resolve_and_save
from analysis.my_deck_classifier import classify_my_deck

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPLAY_DIR = ROOT / "data" / "untapped" / "replays"

_FORMAT_MAP = {
    "Traditional_Standard": "standard",
    "Standard": "standard",
    "Traditional_Pioneer": "pioneer",
    "Pioneer": "pioneer",
    "Traditional_Modern": "modern",
    "Modern": "modern",
    "Traditional_Historic": "historic",
    "Historic": "historic",
}


def _iter_replay_paths(replay_dir: Path) -> Iterable[Path]:
    if not replay_dir.exists():
        return []
    return sorted(replay_dir.glob("*.json.gz"))


def _load_replay(path: Path) -> Optional[dict]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _extract_grp_ids(replay: dict) -> tuple[list[int], list[int], str]:
    """Return (my_grp_ids, opp_grp_ids, opp_name).
    Reuses the untapped_opponent_classifier line-stream parser pattern."""
    from scrapers.untapped_opponent_classifier import _extract_json_from_line
    log = replay.get("log", "")
    user_id = replay.get("userId", "")
    my_seat = None
    opp_seat = None
    opp_name = ""
    my_ids: set[int] = set()
    opp_ids: set[int] = set()

    for line in log.split("\n"):
        obj = _extract_json_from_line(line)
        if obj is None:
            continue

        rsp = (obj.get("matchGameRoomStateChangedEvent", {})
                  .get("gameRoomInfo", {})
                  .get("gameRoomConfig", {})
                  .get("reservedPlayers"))
        if rsp:
            for p in rsp:
                if p.get("userId") == user_id:
                    my_seat = p.get("systemSeatId")
                else:
                    opp_seat = p.get("systemSeatId")
                    opp_name = p.get("playerName", "") or opp_name

        gre = obj.get("greToClientEvent", {}).get("greToClientMessages") or []
        for msg in gre:
            if msg.get("type") != "GREMessageType_GameStateMessage":
                continue
            for go in msg.get("gameStateMessage", {}).get("gameObjects", []) or []:
                owner = go.get("ownerSeatId")
                grp = go.get("grpId")
                if grp is None:
                    continue
                if owner == my_seat:
                    my_ids.add(grp)
                elif owner == opp_seat:
                    opp_ids.add(grp)

    return sorted(my_ids), sorted(opp_ids), opp_name


def run(replay_dir: Path | str = DEFAULT_REPLAY_DIR) -> int:
    """Walk replay_dir, write new match_log rows. Returns count of NEW rows
    (existing arena_match_ids are skipped via the unique index)."""
    from db.database import get_connection
    replay_dir = Path(replay_dir)

    # Build a set of arena_match_ids already in match_log for dedup
    with get_connection() as conn:
        existing = {r[0] for r in conn.execute(
            "SELECT arena_match_id FROM match_log WHERE arena_match_id IS NOT NULL"
        )}

    inserted = 0
    for path in _iter_replay_paths(replay_dir):
        replay = _load_replay(path)
        if replay is None:
            continue
        match_id = replay.get("matchId", "")
        if not match_id or match_id in existing:
            continue
        my_ids, opp_ids, opp_name = _extract_grp_ids(replay)
        fmt_raw = replay.get("format", "")
        fmt = _FORMAT_MAP.get(fmt_raw, fmt_raw.lower())
        if not fmt:
            continue

        my_deck_id = classify_my_deck(my_ids, fmt) if my_ids else None

        # Opponent archetype: reuse mtga_log_parser.classify_opponent_deck
        opp_deck = ""
        if opp_ids:
            try:
                from scrapers.mtga_log_parser import classify_opponent_deck
                opp_deck = classify_opponent_deck(opp_ids, fmt) or ""
            except Exception:
                opp_deck = ""

        resolve_and_save(
            event_name="Untapped replay",
            event_date=str(replay.get("matchDate", "")),
            format_name=fmt,
            round_num=0,
            my_deck_id=my_deck_id,
            opp_deck=opp_deck if opp_deck != "Unknown" else "",
            result=str(replay.get("matchResult", "")),
            source="untapped",
            opp_name=opp_name,
            opp_grp_ids=opp_ids,
            arena_match_id=match_id,
        )
        existing.add(match_id)
        inserted += 1
    return inserted
