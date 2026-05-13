"""
scrapers/untapped_opponent_classifier.py -- attach opponent-archetype data to
Untapped replays.

Each Untapped replay JSON contains the raw MTGA cross-thread log under
`replay['log']` (a single string with newline-separated log lines). The log
includes MatchGameRoomStateChangedEvent (reservedPlayers + seats) and
GREMessageType_GameStateMessage events (gameObjects with ownerSeatId + grpId).

This module:
  1. Streams the log line by line (efficient on large replays)
  2. Finds the user's seat from reservedPlayers (matched on replay.userId)
  3. Collects unique grpIds owned by the opponent's seat
  4. Classifies the archetype using mtga_log_parser.classify_opponent_deck

After backfill_sb_plans() runs, every row in untapped_sideboard_plans has an
opponent_archetype column, enabling per-matchup SB plan queries.
"""

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mtg_meta.db"
REPLAY_DIR = ROOT / "data" / "untapped" / "replays"


def _extract_json_from_line(line: str) -> Optional[dict]:
    """Match the existing mtga_log_parser._extract_json_from_line contract.
    JSON is at the start of the line OR after a UnityCrossThreadLogger prefix."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    idx = line.find("{")
    if idx > 0:
        try:
            return json.loads(line[idx:])
        except json.JSONDecodeError:
            return None
    return None


def extract_opp_grp_ids(replay_path: Path, my_user_id: str) -> tuple:
    """Read a gzipped Untapped replay; return (opp_name, opp_grp_ids: list[int]).

    Returns ('', []) on failure (file missing, parse error, no opponent found).
    """
    if not Path(replay_path).exists():
        return "", []

    opp_seat = None
    opp_name = ""
    opp_grp_ids = set()

    try:
        with gzip.open(replay_path, "rt", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception:
        return "", []

    # The replay JSON has a single 'log' string. Iterate its newline-separated lines.
    log_str = data.get("log", "")
    if not log_str:
        return "", []

    for line in log_str.splitlines():
        payload = _extract_json_from_line(line)
        if payload is None:
            continue

        # MatchGameRoomStateChangedEvent -- find seats once
        if opp_seat is None:
            evt = payload.get("matchGameRoomStateChangedEvent")
            if evt:
                config = evt.get("gameRoomInfo", {}).get("gameRoomConfig", {})
                players = config.get("reservedPlayers", []) or []
                for p in players:
                    if p.get("userId") and p.get("userId") != my_user_id:
                        opp_name = p.get("playerName", "") or ""
                        opp_seat = p.get("systemSeatId")
                        break

        # GameStateMessage gameObjects -- collect opp's played grpIds
        if opp_seat is not None:
            gre = payload.get("greToClientEvent")
            if gre:
                for msg in gre.get("greToClientMessages", []) or []:
                    if msg.get("type") != "GREMessageType_GameStateMessage":
                        continue
                    gs = msg.get("gameStateMessage", {}) or {}
                    for go in gs.get("gameObjects", []) or []:
                        if go.get("ownerSeatId") == opp_seat:
                            grp = go.get("grpId")
                            if grp and grp > 0:
                                opp_grp_ids.add(grp)

    return opp_name, sorted(opp_grp_ids)


def _ensure_schema(con: sqlite3.Connection):
    """Add opponent_archetype + opp_grp_ids_json columns to
    untapped_sideboard_plans if absent (and untapped_replays user_id if
    we need it for opp-seat resolution)."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(untapped_sideboard_plans)")}
    if "opponent_archetype" not in cols:
        con.execute(
            "ALTER TABLE untapped_sideboard_plans "
            "ADD COLUMN opponent_archetype TEXT DEFAULT ''"
        )
    if "opp_grp_ids_json" not in cols:
        con.execute(
            "ALTER TABLE untapped_sideboard_plans "
            "ADD COLUMN opp_grp_ids_json TEXT DEFAULT '[]'"
        )
    con.commit()


def _resolve_grp_ids_to_names(con: sqlite3.Connection, grp_ids: list) -> list:
    """Look up GRP IDs in untapped_card_db (24k MTGA cards)."""
    if not grp_ids:
        return []
    ph = ",".join("?" * len(grp_ids))
    rows = con.execute(
        f"SELECT name FROM untapped_card_db WHERE grpid IN ({ph}) AND name IS NOT NULL",
        grp_ids,
    ).fetchall()
    return [r[0] for r in rows]


def _classify_from_card_names(con: sqlite3.Connection, card_names: list,
                              format_name: str = "standard",
                              min_overlap: int = 3,
                              min_ratio: float = 0.30) -> str:
    """Score archetype overlap against decks in mtg_meta.db.

    Adapted from mtga_log_parser.classify_opponent_deck but uses the correct
    deck_cards/cards schema (the existing function references dc.card_name
    which doesn't exist in the current schema).
    """
    if len(card_names) < min_overlap:
        return ""
    seen = set(card_names)

    rows = con.execute(
        """
        SELECT d.archetype, GROUP_CONCAT(DISTINCT c.name) AS cards
        FROM deck_cards dc
        JOIN cards c ON c.id = dc.card_id
        JOIN decks d ON dc.deck_id = d.id
        JOIN events e ON d.event_id = e.id
        WHERE lower(e.format) = ?
          AND d.archetype IS NOT NULL AND d.archetype != ''
        GROUP BY d.archetype
        """,
        (format_name.lower(),),
    ).fetchall()

    best_arch = ""
    best_score = 0.0
    for archetype, cards_str in rows:
        if not cards_str:
            continue
        arch_cards = set(cards_str.split(","))
        overlap = seen & arch_cards
        if len(overlap) < min_overlap:
            continue
        ratio = len(overlap) / len(seen)
        if ratio < min_ratio:
            continue
        score = len(overlap) * ratio
        if score > best_score:
            best_score = score
            best_arch = archetype

    return best_arch


def backfill_sb_plans(format_name: str = "standard", limit: int = None) -> dict:
    """Backfill opponent_archetype + opp_grp_ids_json on untapped_sideboard_plans.

    Each SB plan row gets opp data inherited from its parent replay (one
    classification per replay, applied to all of its plan rows).

    Returns stats: {processed, classified, unknown, missing_replay}.
    """
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)

    # Find replays needing classification (have plans, no opp_archetype set)
    rows = con.execute(
        """
        SELECT DISTINCT p.replay_short_id AS short_id, r.user_id, r.file_path
        FROM untapped_sideboard_plans p
        JOIN untapped_replays r ON r.short_id = p.replay_short_id
        WHERE COALESCE(p.opponent_archetype, '') = ''
        """
    ).fetchall()

    if limit:
        rows = rows[:limit]

    stats = {"processed": 0, "classified": 0, "unknown": 0, "missing_replay": 0}

    for r in rows:
        short_id = r["short_id"]
        user_id = r["user_id"]
        stored_path = r["file_path"] or ""

        # Resolve replay path -- prefer DB stored path, fall back to canonical layout
        replay_path = Path(stored_path) if stored_path else REPLAY_DIR / f"{short_id}.json.gz"
        if not replay_path.exists():
            replay_path = REPLAY_DIR / f"{short_id}.json.gz"
        if not replay_path.exists():
            stats["missing_replay"] += 1
            continue

        opp_name, opp_grp_ids = extract_opp_grp_ids(replay_path, user_id or "")
        card_names = _resolve_grp_ids_to_names(con, opp_grp_ids)
        archetype = _classify_from_card_names(con, card_names, format_name) or "Unknown"

        con.execute(
            "UPDATE untapped_sideboard_plans "
            "SET opponent_archetype = ?, opp_grp_ids_json = ? "
            "WHERE replay_short_id = ?",
            (archetype, json.dumps(opp_grp_ids), short_id),
        )

        stats["processed"] += 1
        if archetype and archetype != "Unknown":
            stats["classified"] += 1
        else:
            stats["unknown"] += 1

    con.commit()
    con.close()
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", default="standard")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    stats = backfill_sb_plans(format_name=args.format, limit=args.limit)
    print(f"Backfill complete: {stats}")
