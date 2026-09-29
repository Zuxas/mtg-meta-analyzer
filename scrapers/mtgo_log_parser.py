"""Parse MTGO's local game files into match records. Pure: no DB, no network.

Sources (all written by the MTGO client under %LOCALAPPDATA%\\Apps\\2.0):
  Match_GameLog_<token>.dat  one file per MATCH; header = u16, str(token), u16,
                             str(token); then entries of int64 .NET ticks,
                             str(author), str(message). str = 7-bit varint
                             length + bytes (.NET BinaryWriter).
  Logs/mtgo.log              current session only: username, exact decks per
                             game, MatchToken <-> MatchID <-> format, board frames.
  CardDataSource/*.xml       offline CatalogID -> card name.

Ideas from github.com/mymtgo (source-available); no code copied.
Match_GameChat_* / PrivateChatChannel_* are deliberately never read.
"""
from __future__ import annotations

import html
import json
import os
import re
import struct
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

_EPOCH = datetime(1, 1, 1)
_TICKS_MASK = 0x3FFFFFFFFFFFFFFF  # DateTime.ToBinary kind bits

CARD_RE = re.compile(r"@\[(.+?)@:(\d+),(\d+):@\]")
_ACTOR_RE = re.compile(r"^@P(?:@P)?(\S+) (.*)$")
_TURN_RE = re.compile(r"^@PTurn (\d+): (\S+)")
_CHOICE_RE = re.compile(r"^@P(\S+) chooses to (play|draw) first\.")
_BEGINS_RE = re.compile(r"^@P(\S+) (?:.* and )?begins the game with (\w+) cards? in hand\.")
_WINS_GAME_RE = re.compile(r"^@P(\S+) wins the game\.")
_CONCEDE_RE = re.compile(r"^@P(\S+) has conceded from the game\.")
_LOSES_GAME_RE = re.compile(r"^@P(\S+) loses the game\.")
_SCORE_RE = re.compile(r"^@P(\S+) (leads|wins) the match (\d+)-(\d+)")
_TIED_RE = re.compile(r"^Match Tied (\d+)-(\d+)")
_JOINED_RE = re.compile(r"^@P@P(\S+) joined the game\.")
_OWN_CARD_VERBS = ("plays ", "casts ", "cycles ", "discards ",
                   "activates an ability of ", "puts triggered ability from ",
                   "puts a triggered ability from ")
_NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten".split())}

FORMAT_CODES = {
    "CSTANDARD": "standard", "CPIONEER": "pioneer", "CMODERN": "modern",
    "CLEGACY": "legacy", "CVINTAGE": "vintage", "CPAUPER": "pauper",
    "CPREMODERN": "premodern", "CCMDR": "commander", "CCMDRDUEL": "commander",
}


# ---------------------------------------------------------------- binary .dat

@dataclass
class GameLog:
    token: str
    entries: list[tuple[datetime, str]] = field(default_factory=list)
    decode_errors: int = 0
    path: str = ""


def _read_str(b: bytes, i: int) -> tuple[str, int]:
    n = shift = 0
    while True:
        x = b[i]
        i += 1
        n |= (x & 0x7F) << shift
        shift += 7
        if x < 0x80:
            break
    if i + n > len(b):
        raise ValueError("string runs past end of file")
    raw = b[i:i + n]
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("cp1252", errors="replace")
    return s, i + n


def read_gamelog(src: bytes | str | os.PathLike) -> GameLog:
    if isinstance(src, (bytes, bytearray)):
        b, path = bytes(src), ""
    else:
        path = str(src)
        b = Path(src).read_bytes()
    i = 2
    token, i = _read_str(b, i)
    i += 2
    _, i = _read_str(b, i)
    log = GameLog(token=token, path=path)
    while i < len(b):
        try:
            if i + 8 > len(b):
                raise ValueError("truncated timestamp")
            ticks = struct.unpack_from("<q", b, i)[0] & _TICKS_MASK
            _, j = _read_str(b, i + 8)
            msg, j = _read_str(b, j)
        except (ValueError, IndexError):
            log.decode_errors += 1
            break
        log.entries.append((_EPOCH + timedelta(microseconds=ticks // 10), msg))
        i = j
    return log


# ---------------------------------------------------------------- match parsing

_PLAYER_LINE_RES = (_JOINED_RE, _BEGINS_RE, _CHOICE_RE, _WINS_GAME_RE, _CONCEDE_RE,
                    _LOSES_GAME_RE, _SCORE_RE,
                    re.compile(r"^@P(\S+) rolled a \d+\."))


def _players(log: GameLog) -> list[str]:
    seen: set[str] = set()
    for _, m in log.entries:
        for rx in _PLAYER_LINE_RES:
            if mm := rx.match(m):
                seen.add(mm.group(1))
                break
    return sorted(seen)


def _new_game(players):
    return {"on_play": None, "winner": None, "end_reason": None,
            "hand_size": {}, "turns": 0, "cards": {p: Counter() for p in players},
            "_objs": set(), "_explicit": None, "_score_winner": None, "_confirmed": False}


def parse_match(log: GameLog, local_player: str | None) -> dict:
    players = _players(log)
    games: list[dict] = []
    names: dict[int, str] = {}
    score: dict[str, int] | None = None
    running = {p: 0 for p in players}
    match_winner: str | None = None
    cur = None
    closed = False  # a score line has already been booked against `cur`

    def open_game():
        nonlocal cur, closed
        cur = _new_game(players)
        closed = False
        games.append(cur)

    for _, m in log.entries:
        for nm, cat, _obj in CARD_RE.findall(m):
            names.setdefault(int(cat), nm)

        if mm := _CHOICE_RE.match(m):
            open_game()
            chooser, choice = mm.groups()
            other = next((p for p in players if p != chooser), None)
            cur["on_play"] = chooser if choice == "play" else other
            continue
        if mm := _BEGINS_RE.match(m):
            if cur is None:
                open_game()
            cur["hand_size"][mm.group(1)] = _NUM_WORDS.get(mm.group(2), 0)
            continue
        if mm := _TURN_RE.match(m):
            if cur is not None:
                cur["turns"] = max(cur["turns"], int(mm.group(1)))
            continue
        if (mm := _SCORE_RE.match(m)) or (mt := _TIED_RE.match(m)):
            if mm:
                leader, verb, a, b = mm.groups()
                other = next((p for p in players if p != leader), None)
                new = {leader: int(a)}
                if other:
                    new[other] = int(b)
                if verb == "wins":
                    match_winner = leader
            else:
                new = {p: int(mt.group(1)) for p in players}
            gained = [p for p in players if new.get(p, 0) > running.get(p, 0)]
            if len(gained) == 1:
                if cur is None or closed:
                    open_game()  # game decided with no play-by-play (e.g. opponent left)
                cur["_score_winner"] = gained[0]
            running.update(new)
            score = dict(running)
            closed = True
            continue
        ended = None
        if mm := _WINS_GAME_RE.match(m):
            ended = (mm.group(1), "win")
        elif mm := _CONCEDE_RE.match(m):
            ended = (next((p for p in players if p != mm.group(1)), None), "concede")
        elif mm := _LOSES_GAME_RE.match(m):
            ended = (next((p for p in players if p != mm.group(1)), None), "loss")
        if ended:
            prev = cur["_explicit"] if cur else None
            # A concede is followed by "<winner> wins the game" -- sometimes
            # AFTER the score line. That confirms the same game, not a new one.
            confirms = (ended[1] == "win" and prev is not None and prev[0] == ended[0]
                        and not cur["_confirmed"])
            if cur is None or (closed and prev is not None and not confirms):
                open_game()
                prev = None
            if prev is None:
                cur["_explicit"] = ended
            if ended[1] == "win":
                cur["_confirmed"] = True
            continue
        if cur is None:
            continue
        if (mm := _ACTOR_RE.match(m)) and mm.group(1) in cur["cards"]:
            actor, rest = mm.groups()
            if rest.startswith(_OWN_CARD_VERBS):
                c = CARD_RE.search(rest)
                if c and int(c.group(3)) not in cur["_objs"]:
                    cur["_objs"].add(int(c.group(3)))
                    cur["cards"][actor][int(c.group(2))] += 1

    mismatch = False
    for g in games:
        explicit = g.pop("_explicit")
        by_score = g.pop("_score_winner")
        g.pop("_objs")
        g.pop("_confirmed")
        g["cards"] = {p: dict(c) for p, c in g["cards"].items()}
        if explicit:
            g["winner"], g["end_reason"] = explicit
            if by_score and by_score != explicit[0]:
                mismatch = True
        elif by_score:
            g["winner"], g["end_reason"] = by_score, "score"
        else:
            g["end_reason"] = "unknown"

    tally = Counter(g["winner"] for g in games if g["winner"])
    # A game with no result that is followed by another game, when MTGO's own
    # score already accounts for every decided game, was RESTARTED and does
    # not count (70692a45: both players re-joined mid game 2, then "wins the
    # match 2-0"). Marked "void" so importers skip it when numbering games.
    if score is not None and sum(score.values()) == sum(tally.values()):
        for g in games[:-1]:
            if g["winner"] is None:
                g["end_reason"] = "void"
    if score is None:
        score_check = "no_score_line"
    elif mismatch or any(tally.get(p, 0) != score.get(p, 0) for p in players):
        score_check = "mismatch"
    else:
        score_check = "ok"

    spectated = local_player not in players
    local = None if spectated else local_player
    opponent = None if spectated else next((p for p in players if p != local), None)
    result = None
    if not spectated:
        # A match counts only when it verifiably finished: MTGO's own
        # "wins the match" line, or a 2-game lead. Logs that stop mid-match
        # (client closed, crash) are "incomplete" -- never a draw.
        final = {p: max((score or {}).get(p, 0), tally.get(p, 0)) for p in players}
        decided =match_winner or next((p for p in players if final.get(p, 0) >= 2), None)
        if decided:
            result = "win" if decided == local else "loss"
        else:
            result = "incomplete"

    return {
        "token": log.token,
        "started_at": log.entries[0][0] if log.entries else None,
        "players": players, "local": local, "opponent": opponent,
        "spectated": spectated, "games": games, "score": score,
        "score_check": score_check, "result": result, "card_names": names,
        "decode_errors": log.decode_errors,
    }


def guess_local_player(logs: list[GameLog]) -> str | None:
    c = Counter(p for log in logs for p in _players(log))
    return c.most_common(1)[0][0] if c else None


# ---------------------------------------------------------------- mtgo.log

_USER_RE = re.compile(r"\(Twitch Info\|Username: ?(\S+)")
_DECK_RE = re.compile(r"Deck Used in Game ID: (\d+)\) (\[.*\])")
_FRAME_RE = re.compile(r"Game Play Status Update for Game ID: (\d+), Match ID: (\d+)")
_CREATE_RE = re.compile(
    r'"MatchToken":"([0-9a-f-]{36})","MatchID":(\d+)[^}]*?"GameStructureCd":"(\w+)"')


def parse_text_log(path: str | os.PathLike) -> dict:
    out = {"username": None, "decks": {}, "game_to_token": {},
           "match_formats": {}, "frames": 0}
    match_token: dict[int, str] = {}
    game_match: dict[int, int] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if out["username"] is None and (mm := _USER_RE.search(line)):
                out["username"] = mm.group(1)
            if mm := _DECK_RE.search(line):
                deck = {"main": {}, "side": {}}
                try:
                    for it in json.loads(mm.group(2)):
                        zone = "side" if it.get("InSideboard") else "main"
                        cid = int(it["CatalogId"])
                        deck[zone][cid] = deck[zone].get(cid, 0) + int(it["Quantity"])
                    out["decks"][int(mm.group(1))] = deck
                except (ValueError, KeyError, TypeError):
                    pass
            if mm := _FRAME_RE.search(line):
                out["frames"] += 1
                game_match[int(mm.group(1))] = int(mm.group(2))
            for tok, mid, code in _CREATE_RE.findall(line):
                match_token[int(mid)] = tok
                out["match_formats"][tok] = format_from_code(code)
    for gid, mid in game_match.items():
        if mid in match_token:
            out["game_to_token"][gid] = match_token[mid]
    return out


def format_from_code(code: str) -> str:
    if code in FORMAT_CODES:
        return FORMAT_CODES[code]
    if code.startswith(("DC", "DH", "S")):
        return "limited"
    return "unknown"


# ---------------------------------------------------------------- card data

_DOC_RE = re.compile(r'DigitalObjectCatalogID="DOC_(\d+)"')
_TEX_RE = re.compile(r'<CARDTEXTURE_NUMBER value="(\d+)"')
_NAMEREF_RE = re.compile(r'<CARDNAME_STRING id="([^"]+)"')
_NAME_RE = re.compile(r'<CARDNAME_STRING_ITEM id="([^"]+)">(.*?)</CARDNAME_STRING_ITEM>')


def load_card_names(card_data_dir: str | os.PathLike) -> dict[str, dict[int, str]]:
    """Two ID spaces: mtgo.log decks/frames use the catalog id (DOC_n); the
    @[Name@:n,obj:@] references in .dat game logs use CARDTEXTURE_NUMBER."""
    d = Path(card_data_dir)
    strings = {k: html.unescape(v) for k, v in _NAME_RE.findall(
        (d / "CARDNAME_STRING.xml").read_text(encoding="utf-8", errors="replace"))}
    catalog: dict[int, str] = {}
    texture: dict[int, str] = {}
    for f in d.glob("client_*.xml"):
        text = f.read_text(encoding="utf-8", errors="replace")
        for block in text.split("<DigitalObject ")[1:]:
            ref = _NAMEREF_RE.search(block)
            if not ref or ref.group(1) not in strings:
                continue
            name = strings[ref.group(1)]
            if mm := _DOC_RE.search(block):
                catalog.setdefault(int(mm.group(1)), name)
            if mm := _TEX_RE.search(block):
                texture.setdefault(int(mm.group(1)), name)
    return {"catalog": catalog, "texture": texture}


def is_token_name(name: str) -> bool:
    return name.endswith(" Token")


# ---------------------------------------------------------------- mtgo_game_history

def _lst(v) -> list:
    if isinstance(v, dict) and "_items" in v:
        return list(v["_items"][: v.get("_size", len(v["_items"]))])
    return []


def _enum(v):
    return v.get("value__") if isinstance(v, dict) else v


def match_kind(m: dict, parent: dict | None) -> str:
    """tournament | league | precon | casual | other.
    precon = MTGO handed you a pre-built deck (DeckCreationStyle 1);
    casual = a player-created room (PlayIntensity 2/4: practice / just for fun)."""
    desc = (m.get("Description") or "").strip()
    if _enum(m.get("DeckCreationStyle")) == 1:
        return "precon"
    if parent:
        return "tournament"
    if desc.startswith("Play up to 5 rounds"):
        return "league"
    if _enum(m.get("PlayIntensity")) in (2, 4):
        return "casual"
    return "other"


def _hist_match(m: dict, parent: dict | None) -> dict:
    gs = m.get("GameStructure") or {}
    return {
        "kind": match_kind(m, parent),
        "id": m.get("Id"),
        "start": m.get("StartTime"),
        "opponents": _lst(m.get("Opponents")),
        "game_wins": m.get("GameWins") or 0,
        "game_losses": m.get("GameLosses") or 0,
        "winners": _lst(m.get("MatchWinners")),
        "losers": _lst(m.get("MatchLosers")),
        "game_ids": [g for g in _lst(m.get("GameIds")) if g],
        "format": format_from_code(gs.get("GameStructureCd") or ""),
        "event": ((parent or {}).get("Description") or m.get("Description") or "").strip(),
        "round": m.get("Round") or 0,
        "tournament_id": (parent or {}).get("Id"),
    }


def flatten_history(root: dict) -> list[dict]:
    """HistoricalTournament -> its nested matches (event name from the parent);
    standalone HistoricalMatch -> itself. GameWins/GameLosses are the local
    player's."""
    out = []
    for it in _lst(root):
        if not isinstance(it, dict):
            continue
        cls = it.get("__class__", "")
        if cls.endswith(".HistoricalTournament"):
            out += [_hist_match(m, it) for m in _lst(it.get("Matches")) if isinstance(m, dict)]
        elif cls.endswith(".HistoricalMatch"):
            out.append(_hist_match(it, None))
    return out


def read_game_history(path: str | os.PathLike) -> list[dict]:
    from scrapers import nrbf
    return flatten_history(nrbf.loads(Path(path).read_bytes()))


def link_history(match: dict, history: list[dict],
                 window: timedelta = timedelta(minutes=30)) -> dict | None:
    """Numeric .dat names are game ids; GUID-named ones link by opponent + time."""
    tok = match["token"]
    if tok.isdigit():
        gid = int(tok)
        for h in history:
            if gid in h["game_ids"]:
                return h
    opp, start = match.get("opponent"), match.get("started_at")
    if not opp or start is None:
        return None
    best, best_dt = None, window
    for h in history:
        if opp in h["opponents"] and h["start"] is not None:
            dt = abs(h["start"] - start)
            if dt <= best_dt:
                best, best_dt = h, dt
    return best


def history_result(h: dict, local: str) -> str:
    if local in h["winners"]:
        return "win"
    if local in h["losers"]:
        return "loss"
    return "incomplete"


# ---------------------------------------------------------------- discovery

def discover_sources(root: str | os.PathLike | None = None) -> dict:
    base = Path(root or os.path.expandvars(r"%LOCALAPPDATA%\Apps\2.0"))
    installs = sorted(base.glob("Data/*/*/mtgo..tion_*"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    appfiles = [d for inst in installs for d in inst.glob("Data/AppFiles/*") if d.is_dir()]
    card_dirs = [inst / "Data" / "CardDataSource" for inst in installs
                 if (inst / "Data" / "CardDataSource" / "CARDNAME_STRING.xml").exists()]
    logs = sorted(base.glob("*/*/mtgo..tion_*/Logs/mtgo.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return {"appfiles": appfiles, "card_data": card_dirs[0] if card_dirs else None,
            "logs": logs}


def unique_gamelogs(dirs) -> list[Path]:
    """One path per match token across installs (newest copy wins)."""
    best: dict[str, Path] = {}
    for d in dirs:
        for f in Path(d).glob("Match_GameLog_*.dat"):
            tok = f.stem[len("Match_GameLog_"):]
            if tok not in best or f.stat().st_size > best[tok].stat().st_size:
                best[tok] = f
    return sorted(best.values())


# ---------------------------------------------------------------- gate report

def corpus_report(paths, local_player: str | None = None) -> dict:
    logs, failures = [], []
    for f in paths:
        try:
            log = read_gamelog(f)
        except Exception as e:  # noqa: BLE001 -- every failure is reported
            failures.append((str(f), repr(e)))
            continue
        if log.decode_errors:
            failures.append((str(f), f"{log.decode_errors} entry decode error(s)"))
        logs.append(log)
    local = local_player or guess_local_player(logs)
    matches = [parse_match(log, local) for log in logs if log.entries]
    played = [m for m in matches if not m["spectated"]]
    scored = [m for m in played if m["score_check"] != "no_score_line"]
    agree = [m for m in scored if m["score_check"] == "ok"]
    n = len(list(paths)) if not isinstance(paths, list) else len(paths)
    return {
        "files": n,
        "parse_rate": (n - len(failures)) / n if n else 1.0,
        "failures": failures,
        "empty": sum(1 for log in logs if not log.entries),
        "local_player": local,
        "matches": len(matches),
        "spectated": len(matches) - len(played),
        "played": played,
        "score_lines": len(scored),
        "score_agreement": len(agree) / len(scored) if scored else 1.0,
        "mismatches": [m["token"] for m in scored if m["score_check"] != "ok"],
        "unknown_games": sum(1 for m in played for g in m["games"]
                             if g["end_reason"] == "unknown"),
    }
