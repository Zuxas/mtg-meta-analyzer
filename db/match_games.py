"""Per-game stats for a match: mulligans, life trajectory, turn count.

One row per (match_log_id, game_num). Source: mtga_log_parser captures
per-game stats from GameStateMessage walks of Player.log; this module
persists them and provides aggregations.

Public API:
    save_stats_for_match(match_log_id, per_game_stats) -> int
        per_game_stats: dict keyed by game_num -> stat dict
        Returns count of rows written/updated.

    get_stats_for_match(match_log_id) -> list[dict]
        One dict per game (sorted by game_num).

    classify_game(stat: dict, my_won: bool) -> str
        Returns 'blowout', 'close', or 'normal' based on end-life gap.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from db.database import get_connection


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS match_log_games (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        match_log_id    INTEGER NOT NULL,
        game_num        INTEGER NOT NULL,
        my_life_min     INTEGER,
        my_life_end     INTEGER,
        opp_life_min    INTEGER,
        opp_life_end    INTEGER,
        n_turns         INTEGER,
        my_mull_to      INTEGER,
        opp_mull_to     INTEGER,
        UNIQUE (match_log_id, game_num)
    );

    CREATE INDEX IF NOT EXISTS idx_match_games_match
        ON match_log_games(match_log_id);
"""


def _ensure_table(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = get_connection()
    try:
        conn.executescript(_CREATE_SQL)
        conn.commit()
    finally:
        if own:
            conn.close()


def save_stats_for_match(match_log_id: int,
                         per_game_stats: dict) -> int:
    """Persist per-game stats dict (keyed by game_num) for a match.
    Idempotent on (match_log_id, game_num).
    Returns count of rows written/updated."""
    if not per_game_stats:
        return 0
    written = 0
    with get_connection() as conn:
        _ensure_table(conn)
        for game_num, s in per_game_stats.items():
            conn.execute(
                "INSERT INTO match_log_games "
                "(match_log_id, game_num, my_life_min, my_life_end, "
                " opp_life_min, opp_life_end, n_turns, my_mull_to, "
                " opp_mull_to) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(match_log_id, game_num) DO UPDATE SET "
                "  my_life_min = excluded.my_life_min, "
                "  my_life_end = excluded.my_life_end, "
                "  opp_life_min = excluded.opp_life_min, "
                "  opp_life_end = excluded.opp_life_end, "
                "  n_turns = excluded.n_turns, "
                "  my_mull_to = excluded.my_mull_to, "
                "  opp_mull_to = excluded.opp_mull_to",
                (
                    match_log_id, int(game_num),
                    s.get("my_life_min"), s.get("my_life_end"),
                    s.get("opp_life_min"), s.get("opp_life_end"),
                    s.get("n_turns"), s.get("my_mull_to"), s.get("opp_mull_to"),
                ),
            )
            written += 1
        conn.commit()
    return written


def get_stats_for_match(match_log_id: int) -> list[dict]:
    with get_connection() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT game_num, my_life_min, my_life_end, opp_life_min, "
            "       opp_life_end, n_turns, my_mull_to, opp_mull_to "
            "FROM match_log_games WHERE match_log_id = ? "
            "ORDER BY game_num",
            (match_log_id,),
        ).fetchall()
    return [
        {
            "game_num": r[0],
            "my_life_min": r[1], "my_life_end": r[2],
            "opp_life_min": r[3], "opp_life_end": r[4],
            "n_turns": r[5],
            "my_mull_to": r[6], "opp_mull_to": r[7],
        }
        for r in rows
    ]


def classify_game(stat: dict, my_won: bool) -> str:
    """Decisive-vs-close-vs-normal classifier, judged from the WINNER's
    perspective (the loser is always at 0 — useless signal).

    close   : winner ended at <=3 life -- nailbiter, could have gone either way
    blowout : winner ended at >=15 life -- never threatened
    normal  : winner ended between 4 and 14 life
    """
    if my_won:
        winner_end = stat.get("my_life_end")
    else:
        winner_end = stat.get("opp_life_end")
    if winner_end is None:
        return "normal"
    if winner_end <= 3:
        return "close"
    if winner_end >= 15:
        return "blowout"
    return "normal"


def keep_stats_for_deck(my_deck_id: int) -> dict:
    """Aggregate mulligan/keep stats across all games piloting this deck.

    Returns: {
        n_games, kept_on_7, mull_to_6, mull_to_5, mull_to_4, mull_to_3_or_less,
        win_rate_by_mull: {keep7: x.xx, m6: x.xx, ...}
    }
    """
    with get_connection() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            """
            SELECT g.my_mull_to,
                   CASE WHEN g.game_num = 1 AND m.g1_result = 'win' THEN 1
                        WHEN g.game_num = 2 AND m.g2_result = 'win' THEN 1
                        WHEN g.game_num = 3 AND m.g3_result = 'win' THEN 1
                        ELSE 0 END AS won
            FROM match_log_games g
            JOIN match_log m ON m.id = g.match_log_id
            WHERE m.my_deck_id = ? AND g.my_mull_to IS NOT NULL
            """,
            (my_deck_id,),
        ).fetchall()

    buckets = {7: [0, 0], 6: [0, 0], 5: [0, 0], 4: [0, 0], 3: [0, 0]}
    for mull_to, won in rows:
        key = mull_to if mull_to in buckets else 3  # 3-or-less bucket
        buckets[key][1] += 1
        if won:
            buckets[key][0] += 1

    result = {"n_games": len(rows)}
    for key, (w, total) in buckets.items():
        label = f"keep_{key}" if key == 7 else f"mull_to_{key}"
        result[label] = {"wins": w, "games": total,
                         "wr": (w / total) if total else 0.0}
    return result
