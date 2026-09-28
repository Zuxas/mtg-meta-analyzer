"""MTGO match -> the event-stream dict the replay viewer already consumes.

Two MTGO sources per match (spec harness/specs/2026-09-28-mtgo-replay-viewer.md):
  Match_GameLog_<token>.dat   every match: timestamped actions, `Turn N:` markers
  mtgo.log board frames       sessions we captured: every card's zone, life,
                              hand/library counts (no turn/phase, no tapped/counters)
Text events come from the .dat; board events are frame-to-frame diffs; the two
are merged by time. Opponent hand contents are never in a frame (hidden info).

Card ids here are MTGO ids, NOT Arena grpids: board_diff carries grpid=None
(images resolve by name) and the catalog id under `mtgo_catalog`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from scrapers import mtgo_log_parser as p

SCHEMA = "mtgo-2"  # bump on any builder change: older caches are rebuilt
_OPENER_RE = re.compile(r"^@P(?:@P)?\S+ (?:joined the game|rolled a \d+|chooses to (?:play|draw) first)")
_FRAME_RE = re.compile(
    r"^(\d\d):(\d\d):(\d\d) .*?Game Play Status Update for Game ID: (\d+), Match ID: (\d+)[^)]*\) (\{.*)$")
_ZONES = {"Battlefield": "battlefield", "Graveyard": "graveyard", "Exile": "exile",
          "LocalExileCanBePlayed": "exile", "Hand": "hand", "Stack": "stack",
          "Library": "library", "Command": "command"}
_KINDS = (("plays ", "play_land"), ("casts ", "cast_spell"),
          ("activates an ability of ", "activate_ability"),
          ("puts triggered ability from ", "trigger_ability"),
          ("puts a triggered ability from ", "trigger_ability"),
          ("put triggered ability from ", "trigger_ability"),
          ("blocks ", "block_declared"), ("draws ", "draw_card"),
          ("mulligans ", "mulligan_decision"), ("wins the game", "game_end"),
          ("has conceded", "game_end"), ("loses the game", "game_end"))


def clean_text(msg: str) -> str:
    s = p.CARD_RE.sub(lambda m: m.group(1), msg)
    return s.replace("@P@P", "").replace("@P", "").strip()


# ---------------------------------------------------------------- frames

def load_frames(paths) -> dict[int, list]:
    """{game_id: [(h, m, s, players, cards), ...]} with repeats dropped."""
    games: dict[int, list] = {}
    last: dict[int, str] = {}
    seen: set = set()  # the snapshot and the live log can hold the SAME session
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "Game Play Status Update" not in line:
                    continue
                m = _FRAME_RE.match(line)
                if not m:
                    continue
                gid, body = int(m.group(4)), m.group(6)
                key = (gid, m.group(1), m.group(2), m.group(3), body)
                if last.get(gid) == body or key in seen:
                    continue
                seen.add(key)
                try:
                    d = json.loads(body)
                except ValueError:
                    continue
                last[gid] = body
                games.setdefault(gid, []).append(
                    (int(m.group(1)), int(m.group(2)), int(m.group(3)),
                     d.get("Players") or [], d.get("Cards") or []))
    return games


def _at(day: datetime, h: int, mi: int, s: int, near: datetime) -> datetime:
    """Frame clock time -> datetime on the day that puts it nearest `near`."""
    base = day.replace(hour=h, minute=mi, second=s, microsecond=0)
    return min((base + timedelta(days=k) for k in (-1, 0, 1)), key=lambda t: abs(t - near))


def games_for_match(frames: dict, names: set, start: datetime, end: datetime,
                    slack: timedelta = timedelta(minutes=10)) -> list[int]:
    """Frame game ids of this match, in play order: same two players, inside the window."""
    hits = []
    for gid, fr in frames.items():
        if not fr or {pl.get("Name") for pl in fr[0][3]} != names:
            continue
        t0 = _at(start, *fr[0][:3], near=start)
        if start - slack <= t0 <= end + slack:
            hits.append((t0, gid))
    return [gid for _t, gid in sorted(hits)]


def frame_diff(prev: dict, cards: list, my_seat: int, names: dict) -> tuple[list, dict]:
    """Board diffs from one frame to the next. prev/next: {card id: (zone, ctrl, cat)}."""
    cur, diffs = {}, []
    for c in cards:
        zone = _ZONES.get(c.get("Zone"))
        if zone is None:
            continue
        cid, cat, ctrl = c.get("Id"), c.get("CatalogID"), c.get("Controller")
        cur[cid] = (zone, ctrl, cat)
        if prev.get(cid) != cur[cid]:
            diffs.append({"instance_id": cid, "grpid": None, "mtgo_catalog": cat,
                          "card": names.get(cat), "known": True,
                          "controller": "you" if ctrl == my_seat else "opp",
                          "from": (prev.get(cid) or (None,))[0], "to": zone})
    for cid, (zone, ctrl, cat) in prev.items():
        if cid not in cur:
            diffs.append({"instance_id": cid, "grpid": None, "mtgo_catalog": cat,
                          "card": names.get(cat), "known": True,
                          "controller": "you" if ctrl == my_seat else "opp",
                          "from": zone, "to": None})
    return diffs, cur


# ---------------------------------------------------------------- stream

def build_stream(log: "p.GameLog", local: str, frames: dict, names: dict) -> dict:
    """names: {"catalog": {...}, "texture": {...}} from load_card_names."""
    players = p._players(log)
    opp = next((x for x in players if x != local), "Opp")
    entries = log.entries
    start = entries[0][0] if entries else datetime.now()
    end = entries[-1][0] if entries else start
    game_ids = games_for_match(frames, {local, opp}, start, end)

    # Canonical seats: you = 0, opponent = 1. MTGO reassigns Player Ids between
    # games, so each frame is mapped by NAME (a fixed Id put your own game-2
    # hand on the opponent's side).
    my_seat, opp_seat = 0, 1
    seat_of = {local: my_seat, opp: opp_seat}

    # text events from the .dat
    timed: list[tuple] = []
    game, turn, active, ended = 0, None, None, True
    for ts, msg in entries:
        is_end = bool(p._WINS_GAME_RE.match(msg) or p._CONCEDE_RE.match(msg)
                      or p._LOSES_GAME_RE.match(msg) or p._SCORE_RE.match(msg)
                      or p._TIED_RE.match(msg))
        # A game starts at an OPENING line (joined / rolled / chooses to play|draw)
        # after the previous game ended -- any other stray line between a win and
        # the score line stays with the game that just ended. A log that starts
        # mid-game opens game 1 at its first line.
        if ended and (_OPENER_RE.match(msg) or game == 0):
            game, turn, active, ended = game + 1, None, None, False
        if is_end:
            ended = True
        if m := p._TURN_RE.match(msg):
            turn, active = int(m.group(1)), seat_of.get(m.group(2))
        actor, kind, card, texture = None, "raw", None, None
        if mm := p._ACTOR_RE.match(msg):
            actor = seat_of.get(mm.group(1))
            rest = mm.group(2)
            if rest.startswith("is being attacked by"):
                kind, actor = "attack_declared", (opp_seat if actor == my_seat else my_seat)
            else:
                kind = next((k for pre, k in _KINDS if rest.startswith(pre)), "raw")
        c = p.CARD_RE.search(msg)
        if c:
            card, texture = names["texture"].get(int(c.group(2)), c.group(1)), int(c.group(2))
        details = {"text": clean_text(msg), "mtgo_texture": texture}
        if kind == "attack_declared":
            details["attackers"] = [{"name": names["texture"].get(int(t), n)}
                                    for n, t, _o in p.CARD_RE.findall(msg)]
        if kind == "game_end":
            details["reason"] = "concede" if "conceded" in msg else "win"
        timed.append((ts, 0, {"game_num": max(game, 1), "turn_num": turn, "active_seat": active,
                              "actor_seat": actor, "kind": kind, "card_name": card,
                              "details": details, "board_diff": []}))

    # board events from frames
    for g_index, gid in enumerate(game_ids, start=1):
        prev: dict = {}
        prev_life = None
        for h, mi, s, pls, cards in frames[gid]:
            ts = _at(start, h, mi, s, near=start)
            local_id = next((pl.get("Id") for pl in pls if pl.get("Name") == local), None)
            if local_id is None:
                continue
            side = lambda pl: "you" if pl.get("Id") == local_id else "opp"  # noqa: E731
            diffs, prev = frame_diff(prev, cards, local_id, names["catalog"])
            life = {side(pl): pl.get("Life") for pl in pls}
            counts = {side(pl): {"hand": pl.get("HandCount"), "library": pl.get("LibraryCount")}
                      for pl in pls}
            if not diffs and life == prev_life:
                continue
            moved = [d for d in diffs if d["to"] != d["from"]]
            text = ", ".join(f"{d['card'] or '?'} -> {d['to'] or 'gone'}" for d in moved[:4])
            if len(moved) > 4:
                text += f" (+{len(moved) - 4} more)"
            kind = "zone_change" if diffs else "life_change"
            det = {"text": text or "life change", "frame_game_id": gid}
            if kind == "life_change":
                you_d = (life.get("you") or 0) - ((prev_life or life).get("you") or 0)
                det.update(delta=you_d, to=life.get("you"))
            timed.append((ts, 1, {"game_num": g_index, "turn_num": None, "active_seat": None,
                                  "actor_seat": None, "kind": kind,
                                  "card_name": moved[0]["card"] if len(moved) == 1 else None,
                                  "details": det, "board_diff": diffs,
                                  "life_after": life, "counts_after": counts}))
            prev_life = life

    timed.sort(key=lambda x: (x[0], x[1]))
    events, cur_turn, cur_active, life_now, cur_game = [], None, None, None, None
    for seq, (ts, _o, ev) in enumerate(timed):
        if ev["game_num"] != cur_game:  # a new game starts with no turn yet
            cur_game, cur_turn, cur_active = ev["game_num"], None, None
        if ev["kind"] != "zone_change" and ev["kind"] != "life_change":
            cur_turn, cur_active = ev["turn_num"], ev["active_seat"]
        else:
            ev["turn_num"], ev["active_seat"] = cur_turn, cur_active
        life_now = ev.get("life_after") or life_now
        ev.setdefault("life_after", life_now)
        ev.update(seq=seq, timestamp=ts.isoformat(), game_state_id=None, phase=None, step=None,
                  priority_seat=None, targets=[], mana_pool_after=None, stack_after=[],
                  card_grpid=None, log_offset=None)
        events.append(ev)

    return {
        "source": "mtgo", "mtgo_match_id": log.token, "schema_version": SCHEMA,
        "capabilities": {"board": bool(game_ids), "zone_counts": bool(game_ids),
                         "phases": False, "tapped": False, "notes": False},
        "match_meta": {"opp_name": opp, "games_with_board": len(game_ids),
                       "started": start.isoformat()},
        "my_seat": my_seat, "opp_seat": opp_seat, "opp_name": opp, "events": events,
    }


# ---------------------------------------------------------------- discovery + cache

def _cache_path(token: str) -> Path:
    from db import database
    return Path(database.DB_PATH).parent / "match_replays_mtgo" / f"{token}.json"


def build_mtgo_event_stream(token: str, force_refresh: bool = False) -> dict | None:
    cache = _cache_path(token)
    if cache.exists() and not force_refresh:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("schema_version") == SCHEMA:
                return cached
        except ValueError:
            pass
    from scrapers.mtgo_snapshot import raw_root
    raw = raw_root()
    src = p.discover_sources()
    dat = next((f for d in [*sorted(raw.glob("*")), *src["appfiles"]]
                for f in [Path(d) / f"Match_GameLog_{token}.dat"] if f.exists()), None)
    if dat is None:
        return None
    log = p.read_gamelog(dat)
    logs = sorted(raw.glob("*/mtgo*.log")) + list(src["logs"])
    texts = [p.parse_text_log(f) for f in logs]
    local = next((t["username"] for t in texts if t["username"]), None) or p.guess_local_player([log])
    names = p.load_card_names(src["card_data"]) if src["card_data"] else {"catalog": {}, "texture": {}}
    stream = build_stream(log, local, load_frames(logs), names)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(stream), encoding="utf-8")
    return stream
