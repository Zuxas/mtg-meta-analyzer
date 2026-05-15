"""On-demand turn-by-turn match transcript builder.

Re-parses MTGA Player.log for a single arena_match_id and extracts a
human-readable transcript: cards cast, lands played, attacks, life
changes, mulligan decisions. Caches to
`data/match_replays/<arena_match_id>.json` so subsequent views are
instant.

Public API:
    build_transcript(arena_match_id, force_refresh=False) -> dict | None
        Returns {"match_id": ..., "games": [
            {"game_num": 1, "turns": [
                {"turn": 1, "active_seat": 1, "actions": [str, ...]},
                ...
            ]},
            ...
        ]}
        or None if the match isn't found in the log.

    transcript_cache_path(arena_match_id) -> Path
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "match_replays"
PLAYER_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / ".." / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player.log"
PLAYER_PREV_LOG = Path(os.environ.get("LOCALAPPDATA", "")) / ".." / "LocalLow" / "Wizards Of The Coast" / "MTGA" / "Player-prev.log"


def transcript_cache_path(arena_match_id: str) -> Path:
    return CACHE_DIR / f"{arena_match_id}.json"


def _load_grpid_names(db_path: Path) -> dict[int, str]:
    if not db_path.exists():
        return {}
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute("SELECT grpid, name FROM untapped_card_db").fetchall()
        return {r[0]: r[1] for r in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        con.close()


def _iter_json_blobs(log_path: Path):
    """Yield parsed JSON objects from Player.log lines.

    Player.log alternates between a [UnityCrossThreadLogger] header line
    and a separate JSON line (or sometimes inline). Some JSON spans
    multiple lines. We handle the common cases: inline-with-prefix and
    next-line.
    """
    if not log_path.exists():
        return
    buf_lines = []
    buf_active = False
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if buf_active:
                buf_lines.append(line)
                # Try parse if line looks like end of JSON
                if line.strip() in ("}", "]"):
                    try:
                        obj = json.loads("\n".join(buf_lines))
                        yield obj
                        buf_lines = []
                        buf_active = False
                        continue
                    except json.JSONDecodeError:
                        pass  # keep accumulating
                continue
            # Look for start of inline JSON on the same line as a marker
            i = line.find("{")
            if i >= 0:
                candidate = line[i:]
                try:
                    obj = json.loads(candidate)
                    yield obj
                except json.JSONDecodeError:
                    # multi-line JSON; start buffering
                    buf_lines = [candidate]
                    buf_active = True


def build_transcript(arena_match_id: str,
                     force_refresh: bool = False) -> Optional[dict]:
    """Build (or load cached) action transcript for one match."""
    cache = transcript_cache_path(arena_match_id)
    if cache.exists() and not force_refresh:
        try:
            with open(cache, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass  # rebuild

    grpid_names = _load_grpid_names(ROOT / "data" / "mtg_meta.db")

    # State machine across all matches; we extract only the target match.
    current_match_id = None
    my_user_id = "GCIUQPR6DRC4XL7L2ZTNU2OMNI"  # TODO: pull from preferences
    my_seat: Optional[int] = None
    opp_seat: Optional[int] = None
    opp_name = ""
    games: dict[int, dict] = {}  # game_num -> {"turns": {turn_num: turn_dict}}
    current_game = 1
    current_turn = 0
    prev_life = {}  # seat -> last seen life
    # Track which actions we've already logged this turn (dedup)
    logged_action_keys: set[tuple] = set()

    target_found = False

    for log_path in (PLAYER_LOG, PLAYER_PREV_LOG):
        for obj in _iter_json_blobs(log_path):
            # ── Match state changes ────────────────────────────────
            mrse = obj.get("matchGameRoomStateChangedEvent")
            if mrse:
                room = mrse.get("gameRoomInfo", {})
                cfg = room.get("gameRoomConfig", {})
                match_id = cfg.get("matchId")
                state = room.get("stateType")
                # "Playing" fires repeatedly during a match; we set up
                # state on the FIRST Playing event for our target match.
                if state in ("MatchGameRoomStateType_Playing",
                             "MatchGameRoomStateType_MatchPending"):
                    if match_id != arena_match_id:
                        # Don't reset our state if we're already past
                        # target-match start; just skip non-target events
                        if current_match_id != arena_match_id:
                            current_match_id = None
                        continue
                    if current_match_id == arena_match_id:
                        continue  # already initialized
                    # First time seeing our target match
                    target_found = True
                    current_match_id = match_id
                    my_seat = opp_seat = None
                    opp_name = ""
                    for p in cfg.get("reservedPlayers", []):
                        if p.get("userId") == my_user_id:
                            my_seat = p.get("systemSeatId")
                        else:
                            opp_seat = p.get("systemSeatId")
                            opp_name = p.get("playerName") or opp_name
                    games = {}
                    current_game = 1
                    current_turn = 0
                    prev_life = {}
                    logged_action_keys = set()
                elif state == "MatchGameRoomStateType_MatchCompleted":
                    if match_id == arena_match_id:
                        current_match_id = None  # done; ignore further events
                continue

            if current_match_id != arena_match_id:
                continue

            # ── GRE events ─────────────────────────────────────────
            gre = obj.get("greToClientEvent")
            if not gre:
                continue
            for msg in gre.get("greToClientMessages", []):
                if msg.get("type") != "GREMessageType_GameStateMessage":
                    continue
                gsm = msg.get("gameStateMessage", {})
                gi = gsm.get("gameInfo", {})
                gn = gi.get("gameNumber")
                if gn:
                    if gn != current_game:
                        # New game; reset dedup
                        logged_action_keys = set()
                    current_game = gn
                ti = gsm.get("turnInfo", {})
                tn = ti.get("turnNumber")
                active = ti.get("activePlayer")
                if tn:
                    current_turn = tn

                # Make sure turn entry exists
                game_entry = games.setdefault(current_game, {"turns": {}})
                turn_entry = game_entry["turns"].setdefault(
                    current_turn,
                    {"turn": current_turn, "active_seat": active, "actions": []}
                )
                if active and not turn_entry.get("active_seat"):
                    turn_entry["active_seat"] = active

                # Capture life total changes
                for p in gsm.get("players", []):
                    seat = p.get("systemSeatNumber")
                    lt = p.get("lifeTotal")
                    if seat is None or lt is None:
                        continue
                    last = prev_life.get(seat)
                    if last is not None and lt != last:
                        who = "You" if seat == my_seat else opp_name or "Opponent"
                        delta = lt - last
                        sign = "+" if delta > 0 else ""
                        turn_entry["actions"].append(
                            f"{who} life: {last} → {lt} ({sign}{delta})"
                        )
                    prev_life[seat] = lt

                # Capture actions (cards cast / lands played / abilities)
                for a in gsm.get("actions", []):
                    seat = a.get("seatId")
                    action = a.get("action", {}) or {}
                    atype = action.get("actionType", "")
                    grp = action.get("grpId")
                    instance = action.get("instanceId")
                    key = (current_game, current_turn, seat, atype, grp, instance)
                    if key in logged_action_keys:
                        continue
                    logged_action_keys.add(key)
                    if atype == "ActionType_Activate_Mana":
                        continue  # too noisy
                    name = grpid_names.get(grp, f"grpId:{grp}") if grp else None
                    who = "You" if seat == my_seat else "Opp"
                    if atype == "ActionType_Cast" and name:
                        turn_entry["actions"].append(f"{who} cast {name}")
                    elif atype == "ActionType_Play" and name:
                        turn_entry["actions"].append(f"{who} play {name}")
                    elif atype == "ActionType_Activate_Ability" and name:
                        turn_entry["actions"].append(f"{who} activate {name}")
                    # Otherwise skip (ActionType_Pass, etc.)

    if not target_found:
        return None

    # Render to dict
    out_games = []
    for gn in sorted(games.keys()):
        turns_out = []
        for tn in sorted(games[gn]["turns"].keys()):
            t = games[gn]["turns"][tn]
            if not t["actions"]:
                continue  # skip empty turns
            turns_out.append({
                "turn": tn,
                "active_seat": t.get("active_seat"),
                "active_label": ("You" if t.get("active_seat") == my_seat
                                  else (opp_name or "Opponent")),
                "actions": t["actions"],
            })
        out_games.append({"game_num": gn, "turns": turns_out})

    result = {
        "arena_match_id": arena_match_id,
        "my_seat": my_seat,
        "opp_seat": opp_seat,
        "opp_name": opp_name,
        "games": out_games,
    }

    # Cache
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # best-effort cache

    return result
