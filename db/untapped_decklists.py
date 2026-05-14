"""
Per-player Untapped decklist storage.

Reads game-1 mainboard + sideboard from locally-stored Untapped replay JSON
(`data/untapped/replays/<short_id>.json.gz`) and persists the canonical
decklist into `untapped_decklists` so the GUI can show "what deck did this
Mythic player run" without parsing the replay corpus on every click.

Pure local read. No network calls -- pulls from the existing replay corpus
that `scrapers.untapped_replay_fetcher` already downloaded.

Public API:
    extract_decklist_from_replay(path) -> dict | None
    resolve_grpids(conn, grpid_counts) -> dict[str, int]
    save_decklist(short_id, mainboard, sideboard, archetype, source_path) -> None
    get_decklist(short_id) -> dict | None
    populate_for_short_ids(short_ids, replay_dir=None) -> dict[str, int]
"""
from __future__ import annotations

import gzip
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from db.database import get_connection

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPLAY_DIR = _REPO_ROOT / "data" / "untapped" / "replays"


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS untapped_decklists (
            short_id           TEXT PRIMARY KEY,
            mainboard_json     TEXT NOT NULL,
            sideboard_json     TEXT NOT NULL,
            archetype          TEXT,
            fetched_at         TEXT NOT NULL,
            source_replay_path TEXT
        )
    """)
    conn.commit()


def extract_decklist_from_replay(path: Path) -> Optional[dict]:
    """Parse a local replay JSON.gz, return raw grpId counts for game-1.

    Returns {'mainboard': Counter[grpid], 'sideboard': Counter[grpid]} or None
    if the replay is malformed/unreadable.
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    decks = data.get("decks") or []
    if not decks or not isinstance(decks[0], dict):
        return None

    deck0 = decks[0].get("deck") or {}
    mb_grpids = deck0.get("mainDeck") or []
    sb_grpids = deck0.get("sideboard") or []

    mb = Counter(g for g in mb_grpids if isinstance(g, int) and g > 0)
    sb = Counter(g for g in sb_grpids if isinstance(g, int) and g > 0)
    if not mb:
        return None
    return {"mainboard": mb, "sideboard": sb}


def resolve_grpids(conn: sqlite3.Connection,
                   grpid_counts: dict[int, int]) -> dict[str, int]:
    """grpId -> card name via untapped_card_db, aggregated by name.

    Multiple grpIds can map to the same card name (alt art / reprint),
    so we collapse to a single qty per name.
    """
    if not grpid_counts:
        return {}
    placeholders = ",".join("?" * len(grpid_counts))
    rows = conn.execute(
        f"SELECT grpid, name FROM untapped_card_db "
        f"WHERE grpid IN ({placeholders}) AND name IS NOT NULL",
        list(grpid_counts.keys()),
    ).fetchall()
    name_qty: dict[str, int] = {}
    for row in rows:
        grpid = row[0] if isinstance(row, tuple) else row["grpid"]
        name = row[1] if isinstance(row, tuple) else row["name"]
        name_qty[name] = name_qty.get(name, 0) + grpid_counts.get(grpid, 0)
    return name_qty


def save_decklist(short_id: str,
                  mainboard: dict[str, int],
                  sideboard: dict[str, int],
                  archetype: Optional[str] = None,
                  source_replay_path: Optional[str] = None,
                  conn: Optional[sqlite3.Connection] = None) -> None:
    """Idempotent upsert keyed on short_id."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        _ensure_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO untapped_decklists "
            "(short_id, mainboard_json, sideboard_json, archetype, "
            " fetched_at, source_replay_path) VALUES (?, ?, ?, ?, ?, ?)",
            (
                short_id,
                json.dumps(mainboard, ensure_ascii=False, sort_keys=True),
                json.dumps(sideboard, ensure_ascii=False, sort_keys=True),
                archetype or "",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                source_replay_path or "",
            ),
        )
        conn.commit()
    finally:
        if own_conn:
            conn.close()


def get_decklist(short_id: str,
                 conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    """Return {short_id, mainboard, sideboard, archetype, fetched_at,
    source_replay_path} or None."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT short_id, mainboard_json, sideboard_json, archetype, "
            "       fetched_at, source_replay_path "
            "FROM untapped_decklists WHERE short_id = ?",
            (short_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "short_id": row[0],
            "mainboard": json.loads(row[1]),
            "sideboard": json.loads(row[2]),
            "archetype": row[3] or None,
            "fetched_at": row[4],
            "source_replay_path": row[5] or None,
        }
    finally:
        if own_conn:
            conn.close()


def populate_for_short_ids(short_ids: Iterable[str],
                           replay_dir: Optional[Path] = None,
                           archetype_lookup: Optional[dict[str, str]] = None,
                           skip_existing: bool = True) -> dict[str, int]:
    """Read local replays for each short_id, write a decklist row per success.

    Returns counts: {written, skipped_existing, missing_replay,
                     malformed, no_card_resolution}.
    Aggregate count across all short_ids passed in.
    """
    if replay_dir is None:
        replay_dir = DEFAULT_REPLAY_DIR
    replay_dir = Path(replay_dir)
    archetype_lookup = archetype_lookup or {}

    stats = {"written": 0, "skipped_existing": 0, "missing_replay": 0,
             "malformed": 0, "no_card_resolution": 0}

    with get_connection() as conn:
        _ensure_table(conn)

        existing: set[str] = set()
        if skip_existing:
            existing = {
                r[0] for r in conn.execute(
                    "SELECT short_id FROM untapped_decklists"
                ).fetchall()
            }

        for short_id in short_ids:
            if short_id in existing:
                stats["skipped_existing"] += 1
                continue

            path = replay_dir / f"{short_id}.json.gz"
            if not path.exists():
                stats["missing_replay"] += 1
                continue

            extracted = extract_decklist_from_replay(path)
            if extracted is None:
                stats["malformed"] += 1
                continue

            mb_names = resolve_grpids(conn, dict(extracted["mainboard"]))
            sb_names = resolve_grpids(conn, dict(extracted["sideboard"]))
            if not mb_names:
                stats["no_card_resolution"] += 1
                continue

            save_decklist(
                short_id=short_id,
                mainboard=mb_names,
                sideboard=sb_names,
                archetype=archetype_lookup.get(short_id),
                source_replay_path=str(path),
                conn=conn,
            )
            stats["written"] += 1

    return stats


def populate_for_mythic_leaderboard(replay_dir: Optional[Path] = None,
                                    skip_existing: bool = True) -> dict[str, int]:
    """Walk the latest Mythic leaderboard, write decklists for everyone
    who has a local replay. Convenience wrapper around populate_for_short_ids
    pulling short_id + archetype from v_untapped_latest_entries."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT short_id, archetype_primary FROM v_untapped_latest_entries"
        ).fetchall()
    short_ids = [r[0] for r in rows]
    archetype_lookup = {r[0]: (r[1] or "") for r in rows}
    return populate_for_short_ids(
        short_ids,
        replay_dir=replay_dir,
        archetype_lookup=archetype_lookup,
        skip_existing=skip_existing,
    )


def populate_for_all_local_replays(replay_dir: Optional[Path] = None,
                                   skip_existing: bool = True) -> dict[str, int]:
    """Walk every locally-stored replay and write a decklist for each.

    Archetype is looked up across ALL snapshots in untapped_entries
    (not just the latest) since a replay may have been collected when
    the player was on an older snapshot. Falls back to "" if unknown.
    """
    if replay_dir is None:
        replay_dir = DEFAULT_REPLAY_DIR
    replay_dir = Path(replay_dir)
    short_ids = [p.stem.split(".")[0] for p in replay_dir.glob("*.json.gz")]
    if not short_ids:
        return {"written": 0, "skipped_existing": 0, "missing_replay": 0,
                "malformed": 0, "no_card_resolution": 0}

    archetype_lookup: dict[str, str] = {}
    with get_connection() as conn:
        # Most-recent archetype tag per short_id across all snapshots
        placeholders = ",".join("?" * len(short_ids))
        rows = conn.execute(
            f"SELECT e.short_id, e.archetype_primary "
            f"FROM untapped_entries e "
            f"JOIN untapped_snapshots s ON s.id = e.snapshot_id "
            f"WHERE e.short_id IN ({placeholders}) "
            f"ORDER BY s.id DESC",
            short_ids,
        ).fetchall()
        for r in rows:
            sid = r[0]
            arch = r[1] or ""
            archetype_lookup.setdefault(sid, arch)

    return populate_for_short_ids(
        short_ids,
        replay_dir=replay_dir,
        archetype_lookup=archetype_lookup,
        skip_existing=skip_existing,
    )
