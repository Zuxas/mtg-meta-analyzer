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

from db.database import DB_PATH as CENTRAL_DB_PATH

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(CENTRAL_DB_PATH)
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
    """Add opponent_archetype + opp_grp_ids_json + friendly_archetype
    columns to untapped_sideboard_plans if absent, and create the
    untapped_replay_decks table for per-replay game-1 mainboards."""
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
    if "friendly_archetype" not in cols:
        con.execute(
            "ALTER TABLE untapped_sideboard_plans "
            "ADD COLUMN friendly_archetype TEXT DEFAULT ''"
        )

    # Per-replay game-1 deck composition. One row per (replay, card_name).
    # Source: replay JSON decks[0].deck.mainDeck (list of grpIds, repeated for qty).
    # Mythic-tier by definition -- the replay scraper only collects mythic-ladder players.
    con.execute("""
        CREATE TABLE IF NOT EXISTS untapped_replay_decks (
            replay_short_id TEXT NOT NULL,
            card_name       TEXT NOT NULL,
            quantity        INTEGER NOT NULL,
            archetype       TEXT DEFAULT '',
            PRIMARY KEY (replay_short_id, card_name)
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_replay_decks_archetype
            ON untapped_replay_decks(archetype, card_name)
    """)
    con.commit()


def backfill_replay_decks(format_name: str = "standard", limit: int = None) -> dict:
    """Walk each saved replay, extract game-1 mainboard, resolve grpIds to
    card names, write to untapped_replay_decks. Tags each row with the
    KNN-classified archetype from untapped_sideboard_plans.friendly_archetype
    so we can query 'cards used by Izzet Prowess at Mythic.'

    Returns stats: {processed, cards_written, missing_replay, no_archetype}.
    """
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    _ensure_schema(con)

    # Find replays with classified friendly archetype that we haven't
    # decomposed yet.
    rows = con.execute("""
        SELECT DISTINCT p.replay_short_id AS short_id,
               p.friendly_archetype     AS arch,
               r.file_path              AS file_path
        FROM untapped_sideboard_plans p
        JOIN untapped_replays r ON r.short_id = p.replay_short_id
        WHERE COALESCE(p.friendly_archetype, '') NOT IN ('', 'Unknown')
          AND NOT EXISTS (
              SELECT 1 FROM untapped_replay_decks d
              WHERE d.replay_short_id = p.replay_short_id
          )
    """).fetchall()

    if limit:
        rows = rows[:limit]

    stats = {"processed": 0, "cards_written": 0, "missing_replay": 0,
             "no_archetype": 0}

    for r in rows:
        short_id = r["short_id"]
        archetype = r["arch"]
        stored_path = r["file_path"] or ""

        replay_path = Path(stored_path) if stored_path else REPLAY_DIR / f"{short_id}.json.gz"
        if not replay_path.exists():
            replay_path = REPLAY_DIR / f"{short_id}.json.gz"
        if not replay_path.exists():
            stats["missing_replay"] += 1
            continue

        try:
            with gzip.open(replay_path, "rt", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except Exception:
            stats["missing_replay"] += 1
            continue

        decks = data.get("decks", []) or []
        if not decks or not isinstance(decks[0], dict):
            continue
        main_grp_ids = (decks[0].get("deck", {}) or {}).get("mainDeck", []) or []

        grp_counts: dict = {}
        for g in main_grp_ids:
            if isinstance(g, int) and g > 0:
                grp_counts[g] = grp_counts.get(g, 0) + 1
        if not grp_counts:
            continue

        ph = ",".join("?" * len(grp_counts))
        name_rows = con.execute(
            f"SELECT grpid, name FROM untapped_card_db "
            f"WHERE grpid IN ({ph}) AND name IS NOT NULL",
            list(grp_counts.keys()),
        ).fetchall()

        name_qty: dict = {}
        for row in name_rows:
            name_qty[row["name"]] = name_qty.get(row["name"], 0) + grp_counts[row["grpid"]]
        if not name_qty:
            continue

        for name, qty in name_qty.items():
            con.execute(
                "INSERT OR REPLACE INTO untapped_replay_decks "
                "(replay_short_id, card_name, quantity, archetype) "
                "VALUES (?, ?, ?, ?)",
                (short_id, name, qty, archetype),
            )
        stats["cards_written"] += len(name_qty)
        stats["processed"] += 1

    con.commit()
    con.close()
    return stats


def classify_friendly_deck(replay_path: Path) -> str:
    """Classify the friendly player's game-1 deck via the KNN classifier.

    Returns archetype name (e.g. "Izzet Prowess") or "" if classification
    fails (no model, no card data, or low confidence).
    """
    if not Path(replay_path).exists():
        return ""
    try:
        with gzip.open(replay_path, "rt", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception:
        return ""

    decks = data.get("decks", []) or []
    if not decks:
        return ""

    # decks[0] is a dict: {"game": 1, "deck": {"name", "mainDeck": [grpIds], "sideboard": [grpIds]}}
    # Cards repeat in mainDeck list for quantities.
    first = decks[0]
    if not isinstance(first, dict):
        return ""
    main_grp_ids = (first.get("deck", {}) or {}).get("mainDeck", []) or []

    grp_counts = {}
    for grp in main_grp_ids:
        if isinstance(grp, int) and grp > 0:
            grp_counts[grp] = grp_counts.get(grp, 0) + 1

    if not grp_counts:
        return ""

    # Resolve grpIds -> card names via untapped_card_db
    con = sqlite3.connect(str(DB_PATH))
    try:
        ph = ",".join("?" * len(grp_counts))
        rows = con.execute(
            f"SELECT grpid, name FROM untapped_card_db "
            f"WHERE grpid IN ({ph}) AND name IS NOT NULL",
            list(grp_counts.keys()),
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return ""

    name_counts = {}
    for grpid, name in rows:
        name_counts[name] = name_counts.get(name, 0) + grp_counts[grpid]

    if len(name_counts) < 10:
        # Too few unique cards to classify
        return ""

    try:
        from analysis.knn_classifier import classify_deck
        result = classify_deck(name_counts, format_name="standard")
        if result is None:
            return ""
        archetype, confidence = result
        if confidence < 0.40:
            return ""
        return archetype
    except Exception:
        return ""


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

    # Find replays needing classification (have plans, missing opp OR friendly)
    rows = con.execute(
        """
        SELECT DISTINCT p.replay_short_id AS short_id, r.user_id, r.file_path
        FROM untapped_sideboard_plans p
        JOIN untapped_replays r ON r.short_id = p.replay_short_id
        WHERE COALESCE(p.opponent_archetype, '') = ''
           OR COALESCE(p.friendly_archetype, '') = ''
        """
    ).fetchall()

    if limit:
        rows = rows[:limit]

    stats = {"processed": 0, "opp_classified": 0, "opp_unknown": 0,
             "friend_classified": 0, "friend_unknown": 0, "missing_replay": 0}

    for r in rows:
        short_id = r["short_id"]
        user_id = r["user_id"]
        stored_path = r["file_path"] or ""

        replay_path = Path(stored_path) if stored_path else REPLAY_DIR / f"{short_id}.json.gz"
        if not replay_path.exists():
            replay_path = REPLAY_DIR / f"{short_id}.json.gz"
        if not replay_path.exists():
            stats["missing_replay"] += 1
            continue

        # 1) Opponent classification (from log card observations)
        opp_name, opp_grp_ids = extract_opp_grp_ids(replay_path, user_id or "")
        card_names = _resolve_grp_ids_to_names(con, opp_grp_ids)
        opp_arch = _classify_from_card_names(con, card_names, format_name) or "Unknown"

        # 2) Friendly classification (KNN on game-1 deck)
        friend_arch = classify_friendly_deck(replay_path) or "Unknown"

        con.execute(
            "UPDATE untapped_sideboard_plans "
            "SET opponent_archetype = ?, opp_grp_ids_json = ?, "
            "    friendly_archetype = ? "
            "WHERE replay_short_id = ?",
            (opp_arch, json.dumps(opp_grp_ids), friend_arch, short_id),
        )

        stats["processed"] += 1
        if opp_arch and opp_arch != "Unknown":
            stats["opp_classified"] += 1
        else:
            stats["opp_unknown"] += 1
        if friend_arch and friend_arch != "Unknown":
            stats["friend_classified"] += 1
        else:
            stats["friend_unknown"] += 1

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
