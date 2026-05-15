"""Per-match sideboard plan storage.

A row per (match_log_id, from_game, to_game) capturing what cards the
user brought IN and OUT between consecutive games of a Bo3 match.

Source: mtga_log_parser captures per-game decklists from
ConnectResp (game 1) + SubmitDeckReq (games 2/3); this module diffs
consecutive game decks and persists the result.

Public API:
    save_plans_for_match(match_log_id, per_game_decks) -> int
        per_game_decks: list of {"main": [grpid], "sb": [grpid]}
        Returns count of plan rows inserted/updated.

    get_plans_for_match(match_log_id) -> list[dict]
        Each dict: {from_game, to_game, cards_in: {name: qty},
                    cards_out: {name: qty}, n_swapped}.

    get_plans_for_deck(my_deck_id) -> list[dict]
        Aggregates plans across all matches piloting that deck.
        Each dict: {opp_archetype, total_matches, cards_in: {name: total},
                    cards_out: {name: total}}.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from typing import Optional

from db.database import get_connection


_CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS match_log_sb_plans (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        match_log_id    INTEGER NOT NULL,
        from_game       INTEGER NOT NULL,
        to_game         INTEGER NOT NULL,
        cards_in_json   TEXT NOT NULL DEFAULT '{}',
        cards_out_json  TEXT NOT NULL DEFAULT '{}',
        n_swapped       INTEGER NOT NULL DEFAULT 0,
        UNIQUE (match_log_id, from_game, to_game)
    );

    CREATE INDEX IF NOT EXISTS idx_match_sb_plans_match
        ON match_log_sb_plans(match_log_id);
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


def _resolve_grpids_to_names(conn: sqlite3.Connection,
                              grpids: list[int]) -> dict[int, str]:
    if not grpids:
        return {}
    unique = list(set(grpids))
    placeholders = ",".join("?" * len(unique))
    rows = conn.execute(
        f"SELECT grpid, name FROM untapped_card_db "
        f"WHERE grpid IN ({placeholders}) AND name IS NOT NULL",
        unique,
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _name_counter(grpids: list[int],
                  grpid_to_name: dict[int, str]) -> Counter:
    """grpId list -> Counter of card NAMES (alt-arts merge under one name)."""
    out: Counter = Counter()
    for grp in grpids:
        name = grpid_to_name.get(grp)
        if name:
            out[name] += 1
    return out


def _diff_decks_by_name(main_a: list[int], main_b: list[int],
                        grpid_to_name: dict[int, str]) -> tuple[Counter, Counter]:
    """Diff two decks at the card-NAME level (not grpid). Returns
    (cards_in, cards_out) Counters keyed by card name. Net result: if a
    user changed alt art of all 4 Forests, this returns ({}, {}) -- no
    real sideboard swap happened from the user's perspective."""
    a = _name_counter(main_a, grpid_to_name)
    b = _name_counter(main_b, grpid_to_name)
    return (b - a), (a - b)


def save_plans_for_match(match_log_id: int,
                         per_game_decks: list[dict]) -> int:
    """Compute SB-plan diffs across per_game_decks and persist.

    per_game_decks: list of {"main": [grpid...], "sb": [grpid...]}
                    ordered by game number (game 1 first).
    Idempotent on (match_log_id, from_game, to_game).
    Returns count of plan rows written/updated."""
    if not per_game_decks or len(per_game_decks) < 2:
        return 0

    written = 0
    with get_connection() as conn:
        _ensure_table(conn)
        # Resolve all grpids across all games once
        all_grpids: set[int] = set()
        for d in per_game_decks:
            all_grpids.update(d.get("main", []))
        grpid_to_name = _resolve_grpids_to_names(conn, sorted(all_grpids))

        for i in range(len(per_game_decks) - 1):
            from_game = i + 1
            to_game = i + 2
            main_a = per_game_decks[i].get("main") or []
            main_b = per_game_decks[i + 1].get("main") or []
            in_ctr, out_ctr = _diff_decks_by_name(main_a, main_b, grpid_to_name)
            cards_in = dict(in_ctr)
            cards_out = dict(out_ctr)
            n_swapped = sum(cards_in.values())

            conn.execute(
                "INSERT INTO match_log_sb_plans "
                "(match_log_id, from_game, to_game, cards_in_json, "
                " cards_out_json, n_swapped) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (match_log_id, from_game, to_game) DO UPDATE "
                "SET cards_in_json = excluded.cards_in_json, "
                "    cards_out_json = excluded.cards_out_json, "
                "    n_swapped = excluded.n_swapped",
                (
                    match_log_id, from_game, to_game,
                    json.dumps(cards_in, ensure_ascii=False, sort_keys=True),
                    json.dumps(cards_out, ensure_ascii=False, sort_keys=True),
                    n_swapped,
                ),
            )
            written += 1
        conn.commit()
    return written


def get_plans_for_match(match_log_id: int) -> list[dict]:
    with get_connection() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT from_game, to_game, cards_in_json, cards_out_json, n_swapped "
            "FROM match_log_sb_plans WHERE match_log_id = ? "
            "ORDER BY from_game",
            (match_log_id,),
        ).fetchall()
    return [
        {
            "from_game": r[0],
            "to_game": r[1],
            "cards_in": json.loads(r[2] or "{}"),
            "cards_out": json.loads(r[3] or "{}"),
            "n_swapped": r[4],
        }
        for r in rows
    ]


def get_plans_for_deck(my_deck_id: int) -> list[dict]:
    """Aggregate SB plans across every match piloting this deck, grouped
    by opponent archetype.

    Returns one dict per (opp_archetype): {
        opp_archetype: str,
        total_matches: int,
        cards_in: {name: total_qty_across_plans},
        cards_out: {name: total_qty_across_plans},
    }
    """
    with get_connection() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            """
            SELECT m.opp_deck, p.cards_in_json, p.cards_out_json
            FROM match_log_sb_plans p
            JOIN match_log m ON m.id = p.match_log_id
            WHERE m.my_deck_id = ?
            """,
            (my_deck_id,),
        ).fetchall()

    by_opp: dict[str, dict] = defaultdict(
        lambda: {"total_matches": 0, "cards_in": defaultdict(int),
                 "cards_out": defaultdict(int)}
    )
    for opp, in_json, out_json in rows:
        opp_key = (opp or "").strip() or "(unknown)"
        entry = by_opp[opp_key]
        entry["total_matches"] += 1
        for name, qty in json.loads(in_json or "{}").items():
            entry["cards_in"][name] += qty
        for name, qty in json.loads(out_json or "{}").items():
            entry["cards_out"][name] += qty

    return [
        {
            "opp_archetype": opp,
            "total_matches": v["total_matches"],
            "cards_in": dict(v["cards_in"]),
            "cards_out": dict(v["cards_out"]),
        }
        for opp, v in sorted(by_opp.items(),
                              key=lambda kv: -kv[1]["total_matches"])
    ]
