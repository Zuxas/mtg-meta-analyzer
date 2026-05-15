"""Parse MTGA Player.log for the user's current constructed + limited
rank, and write a snapshot row to rank_snapshots.

Rank data is a standalone JSON blob in Player.log with these top-level
keys:
  constructedSeasonOrdinal, constructedClass, constructedLevel,
  constructedMatchesWon, constructedMatchesLost,
  limitedSeasonOrdinal, limitedLevel, limitedStep,
  limitedMatchesWon, limitedMatchesLost

We find the LAST occurrence (most recent rank) and write one snapshot
per format with NOW as captured_at_utc. Time series builds over
multiple invocations.

Public API:
    capture_current_rank(notes='') -> dict | None
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from db.rank_snapshots import save_snapshot


PLAYER_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / ".." / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
PLAYER_PREV_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / ".." / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player-prev.log"


def _iter_json_blobs(log_path: Path):
    """Yield parsed JSON objects from Player.log lines."""
    if not log_path.exists():
        return
    buf_lines: list[str] = []
    buf_active = False
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if buf_active:
                buf_lines.append(line)
                if line.strip() in ("}", "]"):
                    try:
                        yield json.loads("\n".join(buf_lines))
                        buf_lines = []
                        buf_active = False
                        continue
                    except json.JSONDecodeError:
                        pass
                continue
            i = line.find("{")
            if i >= 0:
                candidate = line[i:]
                try:
                    yield json.loads(candidate)
                except json.JSONDecodeError:
                    buf_lines = [candidate]
                    buf_active = True


def capture_current_rank(notes: str = "") -> Optional[dict]:
    """Scan Player.log for the most recent rank snapshot, write a row to
    `rank_snapshots` for each format.

    Dedup: only inserts when the rank or W-L changed since the most
    recent stored snapshot (per format). Prevents Dashboard refreshes
    from bloating the table with identical rows.

    Returns a summary dict {constructed, limited, snapshot_ids} or None
    if no rank data found.
    """
    latest = None
    for log_path in (PLAYER_LOG, PLAYER_PREV_LOG):
        for obj in _iter_json_blobs(log_path):
            if not isinstance(obj, dict):
                continue
            if "constructedClass" in obj and "constructedSeasonOrdinal" in obj:
                latest = obj  # keep overwriting -- want the latest

    if latest is None:
        return None

    snapshot_ids = {}

    # Dedup: load most recent stored snapshot per format and compare
    from db.rank_snapshots import get_latest as _get_latest_snapshot
    _existing_constructed = _get_latest_snapshot("constructed") or {}
    _existing_limited = _get_latest_snapshot("limited") or {}

    # Constructed -- dedup against most-recent stored row
    if "constructedClass" in latest:
        cls = str(latest.get("constructedClass", "Bronze"))
        lvl = int(latest.get("constructedLevel", 1))
        w = int(latest.get("constructedMatchesWon", 0))
        l = int(latest.get("constructedMatchesLost", 0))
        if (_existing_constructed.get("class") != cls or
                _existing_constructed.get("level") != lvl or
                _existing_constructed.get("wins") != w or
                _existing_constructed.get("losses") != l):
            sid = save_snapshot(
                format_name="constructed",
                season_ordinal=int(latest.get("constructedSeasonOrdinal", 0)),
                class_name=cls, level=lvl, wins=w, losses=l,
                notes=notes,
            )
            snapshot_ids["constructed"] = sid

    # Limited (rank doesn't have an explicit 'class' field; uses level/step.
    # We map level -> class via standard MTGA convention).
    # MTGA limited Bronze=1, Silver=2, Gold=3, Platinum=4, Diamond=5, Mythic=6
    _LIMITED_CLASS_BY_LEVEL = {
        1: "Bronze", 2: "Silver", 3: "Gold",
        4: "Platinum", 5: "Diamond", 6: "Mythic",
    }
    if "limitedLevel" in latest:
        limited_level = int(latest.get("limitedLevel", 1))
        limited_step = int(latest.get("limitedStep", 1))
        limited_class = _LIMITED_CLASS_BY_LEVEL.get(limited_level, "Bronze")
        l_w = int(latest.get("limitedMatchesWon", 0))
        l_l = int(latest.get("limitedMatchesLost", 0))
        if (_existing_limited.get("class") != limited_class or
                _existing_limited.get("level") != limited_step or
                _existing_limited.get("wins") != l_w or
                _existing_limited.get("losses") != l_l):
            sid = save_snapshot(
                format_name="limited",
                season_ordinal=int(latest.get("limitedSeasonOrdinal", 0)),
                class_name=limited_class, level=limited_step,
                wins=l_w, losses=l_l,
                notes=notes,
            )
            snapshot_ids["limited"] = sid

    return {
        "constructed": {
            "class": latest.get("constructedClass"),
            "level": latest.get("constructedLevel"),
            "wins": latest.get("constructedMatchesWon"),
            "losses": latest.get("constructedMatchesLost"),
        },
        "limited": {
            "level": latest.get("limitedLevel"),
            "step": latest.get("limitedStep"),
            "wins": latest.get("limitedMatchesWon"),
            "losses": latest.get("limitedMatchesLost"),
        },
        "snapshot_ids": snapshot_ids,
    }
