"""
MTGA Log Parser — extracts match results from Arena game logs.

Parses Player.log and Player-prev.log to extract:
  - Match results (per-game and overall)
  - Opponent name
  - Play/draw (from die roll)
  - Mulligan counts
  - Deck card IDs (Arena GRP IDs)
  - Event type

Writes results to match_log table via db.match_log.save_match().

Usage:
    python -m scrapers.mtga_log_parser                  # parse current log
    python -m scrapers.mtga_log_parser --all             # parse current + prev log
    python -m scrapers.mtga_log_parser --dry-run         # show matches without saving
    python -m scrapers.mtga_log_parser --resolve-cards   # resolve Arena IDs to card names
    python -m scrapers.mtga_log_parser --summary         # print summary after import
    python -m scrapers.mtga_log_parser --classify-opponents  # re-classify empty opp_deck entries
"""

import json
import os
import re
import time
import argparse
from datetime import datetime
from collections import Counter

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MTGA_LOG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "..", "LocalLow", "Wizards Of The Coast", "MTGA"
)
PLAYER_LOG = os.path.normpath(os.path.join(_MTGA_LOG_DIR, "Player.log"))
PLAYER_PREV_LOG = os.path.normpath(os.path.join(_MTGA_LOG_DIR, "Player-prev.log"))

# Your Arena user ID — used to determine which seat is "you"
MY_USER_ID = "GCIUQPR6DRC4XL7L2ZTNU2OMNI"

# Arena event ID -> human-readable name mapping
EVENT_NAMES = {
    "DirectGameTournamentMode": "Direct Game (Bo3)",
    "DirectGame": "Direct Game (Bo1)",
    "Ladder": "Ranked",
    "Play": "Play",
    "Bot_Match": "Bot Match",
    "Constructed_BestOf3_Ranked": "Ranked (Bo3)",
    "Constructed_BestOf1_Ranked": "Ranked (Bo1)",
    "Traditional_Cons_Event": "Traditional Event",
    "Cons_Event": "Standard Event",
    "Premier_Draft": "Premier Draft",
    "Quick_Draft": "Quick Draft",
}

# Cache for Arena card ID -> card name resolution
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CARD_CACHE_PATH = os.path.join(_PROJECT_ROOT, "data", "arena_card_cache.json")

# MTGA's own card database (SQLite) — authoritative source for GrpId -> name
_MTGA_CARD_DB_DIR = os.path.normpath(os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
    "..",
    "LocalLow/Wizards Of The Coast/MTGA"
))
# Steam install path (from registry) — fallback
_MTGA_INSTALL_PATHS = [
    "F:/SteamLibrary/steamapps/common/MTGA",
    "E:/mtgarena",
]


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def _extract_json_from_line(line: str) -> dict | None:
    """Try to parse JSON from a log line. Lines may have a prefix before the JSON."""
    # Try the whole line first
    line = line.strip()
    if line.startswith("{"):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None
    # Try after the UnityCrossThreadLogger prefix
    idx = line.find("{")
    if idx > 0:
        try:
            return json.loads(line[idx:])
        except json.JSONDecodeError:
            return None
    return None


def _parse_timestamp_from_logger(line: str) -> str | None:
    """Extract timestamp from [UnityCrossThreadLogger] line.
    Format: [UnityCrossThreadLogger]M/D/YYYY H:MM:SS AM/PM"""
    m = re.search(r'\[UnityCrossThreadLogger\](\d+/\d+/\d+ \d+:\d+:\d+ [AP]M)', line)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%m/%d/%Y %I:%M:%S %p")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def parse_log_file(path: str) -> list[dict]:
    """Parse a single MTGA log file and extract match data.

    Returns list of match dicts:
        {
            "match_id": str,
            "date": str (YYYY-MM-DD),
            "opponent": str,
            "my_team_id": int,
            "opp_team_id": int,
            "event_id": str,
            "event_name": str,
            "bo3": bool,
            "game_results": [{"game": int, "winner_team": int, "reason": str}],
            "match_result": "win" | "loss" | "draw",
            "g1_result": "win" | "loss" | "",
            "g2_result": "win" | "loss" | "",
            "g3_result": "win" | "loss" | "",
            "play_draw": "play" | "draw" | "",
            "my_mulligans": {game_num: int},
            "deck_card_ids": [int],
            "sideboard_card_ids": [int],
            "opp_card_ids": [int],  # unique GRP IDs seen from opponent
        }
    """
    if not os.path.exists(path):
        return []

    matches = {}          # match_id -> partial match data
    current_match_id = None
    die_rolls = {}        # match_id -> {seat: roll}
    mulligan_counts = {}  # match_id -> {game_num: count}
    deck_cards = {}       # match_id -> {"main": [], "sb": []}
    match_dates = {}      # match_id -> date string
    current_game_num = {} # match_id -> current game number

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        prev_line = ""
        for line in f:
            line = line.rstrip()

            # Capture date from logger lines
            if "[UnityCrossThreadLogger]" in line and "MatchGameRoomStateChangedEvent" in line:
                date_str = _parse_timestamp_from_logger(line)

            # Try to extract JSON — could be on same line or next line
            data = _extract_json_from_line(line)
            if data is None:
                prev_line = line
                continue

            # --- MatchGameRoomStateChangedEvent ---
            evt = data.get("matchGameRoomStateChangedEvent")
            if evt:
                room_info = evt.get("gameRoomInfo", {})
                config = room_info.get("gameRoomConfig", {})
                match_id = config.get("matchId")
                state_type = room_info.get("stateType", "")

                if match_id and state_type == "MatchGameRoomStateType_Playing":
                    # Match started
                    players = config.get("reservedPlayers", [])
                    my_team = None
                    opp_name = ""
                    opp_team = None
                    event_id = ""

                    for p in players:
                        if p.get("userId") == MY_USER_ID:
                            my_team = p.get("teamId")
                            event_id = p.get("eventId", "")
                        else:
                            opp_name = p.get("playerName", "")
                            opp_team = p.get("teamId")

                    matches[match_id] = {
                        "match_id": match_id,
                        "date": date_str if date_str else "",
                        "opponent": opp_name,
                        "my_team_id": my_team,
                        "opp_team_id": opp_team,
                        "event_id": event_id,
                        "event_name": EVENT_NAMES.get(event_id, event_id),
                        "bo3": False,  # updated when we see matchWinCondition
                        "game_results": [],
                        "match_result": "",
                        "g1_result": "",
                        "g2_result": "",
                        "g3_result": "",
                        "play_draw": "",
                        "my_mulligans": {},
                        "deck_card_ids": [],
                        "sideboard_card_ids": [],
                        "opp_card_ids": [],
                    }
                    current_match_id = match_id
                    mulligan_counts[match_id] = {}
                    current_game_num[match_id] = 1

                elif match_id and state_type == "MatchGameRoomStateType_MatchCompleted":
                    # Match completed — extract final results
                    final = room_info.get("finalMatchResult", {})
                    result_list = final.get("resultList", [])

                    if match_id in matches:
                        m = matches[match_id]
                        game_results = []
                        match_winner = None

                        for r in result_list:
                            if r.get("scope") == "MatchScope_Game":
                                game_results.append({
                                    "game": len(game_results) + 1,
                                    "winner_team": r.get("winningTeamId"),
                                    "reason": r.get("reason", ""),
                                })
                            elif r.get("scope") == "MatchScope_Match":
                                match_winner = r.get("winningTeamId")

                        m["game_results"] = game_results

                        # Determine match result
                        if match_winner == m["my_team_id"]:
                            m["match_result"] = "win"
                        elif match_winner == m["opp_team_id"]:
                            m["match_result"] = "loss"
                        elif match_winner is not None:
                            m["match_result"] = "draw"

                        # Per-game results
                        for gr in game_results:
                            g = gr["game"]
                            if gr["winner_team"] == m["my_team_id"]:
                                res = "win"
                            else:
                                res = "loss"
                            if g == 1:
                                m["g1_result"] = res
                            elif g == 2:
                                m["g2_result"] = res
                            elif g == 3:
                                m["g3_result"] = res

                continue

            # --- GRE events (die rolls, mulligans, deck, game state) ---
            gre = data.get("greToClientEvent")
            if gre and current_match_id and current_match_id in matches:
                m = matches[current_match_id]
                for msg in gre.get("greToClientMessages", []):
                    msg_type = msg.get("type", "")

                    # Die roll — determines play/draw
                    if msg_type == "GREMessageType_DieRollResultsResp":
                        rolls = msg.get("dieRollResultsResp", {}).get("playerDieRolls", [])
                        best_seat = None
                        best_roll = -1
                        my_seat = None
                        for roll in rolls:
                            seat = roll.get("systemSeatId")
                            val = roll.get("rollValue", 0)
                            if val > best_roll:
                                best_roll = val
                                best_seat = seat
                        # Find my seat from reserved players
                        # My team_id == my seat in most cases, but let's be safe
                        # The ConnectResp has systemSeatIds for us
                        # For now: seat 1 = team 1, seat 2 = team 2 (consistent in all observed data)
                        my_seat = m["my_team_id"]
                        if best_seat == my_seat:
                            m["play_draw"] = "play"
                        else:
                            m["play_draw"] = "draw"

                    # Deck submission (in ConnectResp)
                    if msg_type == "GREMessageType_ConnectResp":
                        deck_msg = msg.get("connectResp", {}).get("deckMessage", {})
                        if deck_msg:
                            m["deck_card_ids"] = deck_msg.get("deckCards", [])
                            m["sideboard_card_ids"] = deck_msg.get("sideboardCards", [])

                    # Match win condition (Bo1 vs Bo3)
                    if msg_type == "GREMessageType_GameStateMessage":
                        gs = msg.get("gameStateMessage", {})
                        gi = gs.get("gameInfo", {})
                        if gi.get("matchWinCondition") == "MatchWinCondition_Best2of3":
                            m["bo3"] = True

                        # Track game number for mulligan counting
                        gn = gi.get("gameNumber")
                        if gn:
                            current_game_num[current_match_id] = gn

                        # Track opponent cards from gameObjects
                        opp_seat = m.get("opp_team_id")
                        if opp_seat is not None:
                            for go in gs.get("gameObjects", []):
                                if go.get("ownerSeatId") == opp_seat:
                                    grp_id = go.get("grpId")
                                    if grp_id and grp_id > 0 and grp_id not in m["opp_card_ids"]:
                                        m["opp_card_ids"].append(grp_id)

                        # Track mulligan count from player data
                        for p in gs.get("players", []):
                            if p.get("systemSeatNumber") == m["my_team_id"]:
                                mc = p.get("mulliganCount", 0)
                                if mc > 0:
                                    game = current_game_num.get(current_match_id, 1)
                                    m["my_mulligans"][game] = mc

                    # Mulligan decision
                    if msg_type == "GREMessageType_MulliganReq":
                        pass  # tracked via mulliganCount in game state

            # --- Mulligan response (separate message type) ---
            if "decision" in line and "MulliganOption" in line:
                pass  # mulliganCount in game state is more reliable

    # Filter out incomplete matches (started but never finished)
    complete = [m for m in matches.values() if m["match_result"]]
    return complete


# ---------------------------------------------------------------------------
# Arena card ID resolution
# ---------------------------------------------------------------------------

def _load_card_cache() -> dict:
    """Load the Arena GRP ID -> card name cache from disk."""
    if os.path.exists(_CARD_CACHE_PATH):
        try:
            with open(_CARD_CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_card_cache(cache: dict):
    os.makedirs(os.path.dirname(_CARD_CACHE_PATH), exist_ok=True)
    with open(_CARD_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _rebuild_cache_from_mtga_db() -> dict:
    """Build complete GrpId -> card name mapping from MTGA's own SQLite card database."""
    import sqlite3
    import glob

    for install_path in _MTGA_INSTALL_PATHS:
        raw_dir = os.path.join(install_path, "MTGA_Data", "Downloads", "Raw")
        dbs = glob.glob(os.path.join(raw_dir, "Raw_CardDatabase_*.mtga"))
        if dbs:
            # Use the larger file (more complete)
            db_path = max(dbs, key=os.path.getsize)
            try:
                conn = sqlite3.connect(db_path)
                rows = conn.execute("""
                    SELECT c.GrpId, l.Loc
                    FROM Cards c
                    JOIN Localizations_enUS l ON c.TitleId = l.LocId
                """).fetchall()
                conn.close()

                arena_map = {str(grp_id): name for grp_id, name in rows}
                print(f"Built arena card map from MTGA database: {len(arena_map)} entries")
                _save_card_cache(arena_map)
                return arena_map
            except Exception as e:
                print(f"Error reading MTGA card database: {e}")

    return {}


def resolve_card_ids(card_ids: list[int], use_api: bool = True) -> dict[int, str]:
    """Resolve Arena GRP IDs to card names.

    Resolution order:
      1. Local JSON cache (data/arena_card_cache.json)
      2. MTGA's own card database (SQLite, from game install)
      3. Scryfall API (fallback for any remaining misses)

    Returns {grp_id: card_name} mapping.
    """
    cache = _load_card_cache()
    result = {}
    misses = []

    unique_ids = set(card_ids)
    for cid in unique_ids:
        key = str(cid)
        if key in cache:
            result[cid] = cache[key]
        else:
            misses.append(cid)

    # Try MTGA's own database for any misses
    if misses:
        mtga_map = _rebuild_cache_from_mtga_db()
        if mtga_map:
            cache.update(mtga_map)
            still_missing = []
            for cid in misses:
                key = str(cid)
                if key in cache:
                    result[cid] = cache[key]
                else:
                    still_missing.append(cid)
            misses = still_missing

    # Scryfall API fallback
    if misses and use_api:
        import requests
        print(f"Resolving {len(misses)} remaining IDs via Scryfall API...")
        headers = {
            "User-Agent": "mtg-meta-analyzer/1.0 (personal tournament analysis tool)",
            "Accept": "application/json",
        }
        for cid in misses:
            try:
                resp = requests.get(
                    f"https://api.scryfall.com/cards/arena/{cid}",
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code == 200:
                    card = resp.json()
                    name = card.get("name", f"Unknown ({cid})")
                    cache[str(cid)] = name
                    result[cid] = name
                else:
                    result[cid] = f"Unknown ({cid})"
                time.sleep(0.12)
            except Exception as e:
                result[cid] = f"Unknown ({cid})"
        _save_card_cache(cache)

    elif misses:
        for cid in misses:
            result[cid] = f"Unknown ({cid})"

    return result


def format_decklist(card_ids: list[int], card_map: dict[int, str]) -> str:
    """Format a list of Arena card IDs as a human-readable decklist."""
    counts = Counter()
    for cid in card_ids:
        name = card_map.get(cid, f"Unknown ({cid})")
        counts[name] += 1
    lines = []
    for name, qty in sorted(counts.items()):
        lines.append(f"{qty} {name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Opponent deck classification
# ---------------------------------------------------------------------------

_META_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "mtg_meta.db")


def classify_opponent_deck(opp_card_ids: list[int], format_name: str = "standard") -> str:
    """Classify the opponent's deck archetype from observed card GRP IDs.

    Loads archetypes and their typical card lists from the meta DB, then scores
    overlap against the opponent's observed cards.

    Returns archetype name or "Unknown" if no confident match.
    """
    if not opp_card_ids:
        return "Unknown"

    # Resolve GRP IDs to card names
    card_map = resolve_card_ids(opp_card_ids, use_api=False)
    opp_card_names = set()
    for cid in opp_card_ids:
        name = card_map.get(cid, "")
        if name and not name.startswith("Unknown"):
            opp_card_names.add(name)

    if len(opp_card_names) < 3:
        return "Unknown"

    # Load archetype card lists from DB
    import sqlite3
    if not os.path.exists(_META_DB_PATH):
        return "Unknown"

    try:
        conn = sqlite3.connect(_META_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT d.archetype, GROUP_CONCAT(DISTINCT c.name) AS cards
            FROM deck_cards dc
            JOIN cards c ON c.id = dc.card_id
            JOIN decks d ON dc.deck_id = d.id
            JOIN events e ON d.event_id = e.id
            WHERE e.format = ?
              AND d.archetype IS NOT NULL
              AND d.archetype != ''
            GROUP BY d.archetype
        """, (format_name,)).fetchall()
        conn.close()
    except Exception:
        return "Unknown"

    if not rows:
        return "Unknown"

    # Score each archetype by card overlap
    best_archetype = "Unknown"
    best_score = 0
    best_overlap = 0

    for row in rows:
        archetype = row["archetype"]
        archetype_cards = set(row["cards"].split(",")) if row["cards"] else set()
        if not archetype_cards:
            continue

        overlap = opp_card_names & archetype_cards
        overlap_count = len(overlap)
        overlap_ratio = overlap_count / len(opp_card_names) if opp_card_names else 0

        # Require at least 3 matching cards and >30% of seen cards match
        if overlap_count >= 3 and overlap_ratio > 0.30:
            # Score: weighted by both count and ratio
            score = overlap_count * overlap_ratio
            if score > best_score:
                best_score = score
                best_archetype = archetype
                best_overlap = overlap_count

    return best_archetype


# ---------------------------------------------------------------------------
# DB integration
# ---------------------------------------------------------------------------

def save_matches_to_db(matches: list[dict], format_name: str = "standard",
                       my_deck: str = "") -> int:
    """Save parsed matches to match_log table. Skips duplicates by arena_match_id.

    Uses db.match_log.resolve_and_save() so each row gets:
      - my_deck_id resolved via analysis.my_deck_classifier (when the user's
        deck grpIds overlap a saved_decks entry above the 0.70 threshold)
      - source='mtga_log' for provenance
      - opp_grp_ids_json populated so opponent classification can be redone

    Returns count of newly saved matches.
    """
    from db.match_log import _ensure_table, resolve_and_save
    from db.database import get_connection
    from analysis.my_deck_classifier import classify_my_deck
    from analysis.auto_save_deck import find_or_create_deck, classify_event

    # Ensure arena_match_id column exists
    _ensure_table()
    _ensure_arena_match_id_column()

    # Get existing arena match IDs to avoid duplicates
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT arena_match_id FROM match_log WHERE arena_match_id IS NOT NULL"
        ).fetchall()
    existing_ids = {r["arena_match_id"] for r in rows}

    saved = 0
    for m in matches:
        if m["match_id"] in existing_ids:
            continue

        # Build notes from extra data
        notes_parts = []
        if m["my_mulligans"]:
            mull_str = ", ".join(f"G{g}: mull to {7-c}" for g, c in sorted(m["my_mulligans"].items()))
            notes_parts.append(f"Mulligans: {mull_str}")
        if m["bo3"]:
            notes_parts.append("Bo3")
        if m["deck_card_ids"]:
            notes_parts.append(f"Deck IDs: {len(m['deck_card_ids'])} cards")

        # Auto-classify opponent deck from observed cards
        opp_deck = ""
        opp_card_ids = m.get("opp_card_ids", [])
        if opp_card_ids:
            opp_deck = classify_opponent_deck(opp_card_ids, format_name)

        # Auto-classify my deck against saved_decks via grpId overlap.
        # If no existing saved deck matches, fall back to auto-creating
        # one named after the closest meta archetype.
        my_deck_id = None
        my_grp_ids = m.get("deck_card_ids") or []
        if my_grp_ids:
            try:
                my_deck_id = classify_my_deck(my_grp_ids, format_name)
            except Exception:
                my_deck_id = None
            if my_deck_id is None:
                event_cat = classify_event(m.get("event_name") or "")
                try:
                    my_deck_id = find_or_create_deck(
                        my_grp_ids, format_name, event_cat
                    )
                except Exception:
                    my_deck_id = None

        row_id = resolve_and_save(
            event_name=m["event_name"],
            event_date=m["date"],
            format_name=format_name,
            round_num=0,  # Arena doesn't expose round numbers
            my_deck_id=my_deck_id,
            opp_deck=opp_deck if opp_deck != "Unknown" else "",
            result=m["match_result"],
            source="mtga_log",
            play_draw=m["play_draw"],
            opp_name=m["opponent"],
            g1_result=m["g1_result"],
            g2_result=m["g2_result"],
            g3_result=m["g3_result"],
            notes="; ".join(notes_parts),
            opp_grp_ids=opp_card_ids if opp_card_ids else None,
            arena_match_id=m["match_id"],
        )
        existing_ids.add(m["match_id"])

        saved += 1

    return saved


def _ensure_arena_match_id_column():
    """Add arena_match_id column to match_log if it doesn't exist."""
    from db.database import get_connection
    import sqlite3
    with get_connection() as conn:
        try:
            conn.execute("ALTER TABLE match_log ADD COLUMN arena_match_id TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_match_log_arena_id "
                "ON match_log(arena_match_id)"
            )
        except sqlite3.OperationalError:
            pass  # column already exists


# ---------------------------------------------------------------------------
# Summary / reporting
# ---------------------------------------------------------------------------

def print_summary(matches: list[dict], card_map: dict[int, str] | None = None):
    """Print a human-readable summary of parsed matches."""
    if not matches:
        print("No matches found.")
        return

    wins = sum(1 for m in matches if m["match_result"] == "win")
    losses = sum(1 for m in matches if m["match_result"] == "loss")
    draws = sum(1 for m in matches if m["match_result"] == "draw")
    total = len(matches)

    print(f"\n{'='*60}")
    print(f"MTGA Log Parser - {total} matches found")
    print(f"{'='*60}")
    print(f"Record: {wins}-{losses}" + (f"-{draws}" if draws else ""))
    if wins + losses > 0:
        print(f"Win Rate: {wins/(wins+losses)*100:.1f}%")
    print()

    for m in matches:
        result_icon = {"win": "W", "loss": "L", "draw": "D"}.get(m["match_result"], "?")
        games = ""
        for g in m["game_results"]:
            if g["winner_team"] == m["my_team_id"]:
                games += "W"
            else:
                games += "L"

        pd = {"play": "OTP", "draw": "OTD", "": "???"}.get(m["play_draw"], "???")
        mull_info = ""
        if m["my_mulligans"]:
            mull_info = " | " + ", ".join(
                f"G{g}:mull{c}" for g, c in sorted(m["my_mulligans"].items())
            )

        opp_deck_info = ""
        opp_cards = m.get("opp_card_ids", [])
        if opp_cards:
            opp_deck_info = f" | Opp cards: {len(opp_cards)}"

        print(f"  [{result_icon}] {m['date']} vs {m['opponent']:<20s} "
              f"({games}) {pd} | {m['event_name']}{mull_info}{opp_deck_info}")

    # Deck info
    if matches and matches[0]["deck_card_ids"] and card_map:
        print(f"\nDeck ({len(matches[0]['deck_card_ids'])} cards):")
        print(format_decklist(matches[0]["deck_card_ids"], card_map))
        if matches[0]["sideboard_card_ids"]:
            print(f"\nSideboard ({len(matches[0]['sideboard_card_ids'])} cards):")
            print(format_decklist(matches[0]["sideboard_card_ids"], card_map))

    print()


def generate_knowledge_block(matches: list[dict], card_map: dict[int, str] | None = None) -> str:
    """Generate a harness knowledge block from parsed match data."""
    if not matches:
        return ""

    wins = sum(1 for m in matches if m["match_result"] == "win")
    losses = sum(1 for m in matches if m["match_result"] == "loss")
    total = len(matches)
    dates = sorted(set(m["date"] for m in matches if m["date"]))
    date_range = f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else dates[0] if dates else "unknown"

    lines = [
        "---",
        'title: "MTGA Session Report"',
        'domain: "mtg"',
        f'last_updated: "{datetime.now().strftime("%Y-%m-%d")}"',
        'confidence: "high"',
        'sources: ["mtga-log-parser"]',
        "---",
        "",
        "## Summary",
        f"MTGA session: {total} matches, {wins}-{losses} ({wins/(wins+losses)*100:.1f}% WR)" if wins+losses else f"MTGA session: {total} matches",
        f"Date range: {date_range}",
        "",
        "## Match Results",
    ]

    for m in matches:
        result_icon = {"win": "W", "loss": "L", "draw": "D"}.get(m["match_result"], "?")
        games = "/".join(
            "W" if g["winner_team"] == m["my_team_id"] else "L"
            for g in m["game_results"]
        )
        pd = {"play": "OTP", "draw": "OTD", "": "?"}.get(m["play_draw"], "?")
        lines.append(f"- [{result_icon}] vs {m['opponent']} ({games}) {pd} — {m['event_name']}")

    if card_map and matches[0]["deck_card_ids"]:
        lines.extend(["", "## Deck Submitted"])
        for card_line in format_decklist(matches[0]["deck_card_ids"], card_map).split("\n"):
            lines.append(f"- {card_line}")

    lines.extend([
        "",
        "## Changelog",
        f"- {datetime.now().strftime('%Y-%m-%d')}: Parsed from MTGA Player.log",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reclassify opponent decks
# ---------------------------------------------------------------------------

def _reclassify_opponent_decks(format_name: str = "standard"):
    """Re-process match_log entries with empty opp_deck by re-parsing logs
    for opponent card data and running the classifier."""
    from db.database import get_connection

    # Find matches with empty opp_deck that have arena_match_id
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, arena_match_id, format FROM match_log "
            "WHERE (opp_deck IS NULL OR opp_deck = '') "
            "AND arena_match_id IS NOT NULL"
        ).fetchall()

    if not rows:
        print("No matches with empty opp_deck found.")
        return

    print(f"Found {len(rows)} matches with empty opp_deck. Re-parsing logs...")

    # Parse both log files to get opponent card data
    all_parsed = {}
    for path in [PLAYER_LOG, PLAYER_PREV_LOG]:
        if os.path.exists(path):
            parsed = parse_log_file(path)
            for m in parsed:
                all_parsed[m["match_id"]] = m

    updated = 0
    for row in rows:
        arena_id = row["arena_match_id"]
        fmt = row["format"] or format_name
        if arena_id in all_parsed:
            m = all_parsed[arena_id]
            opp_card_ids = m.get("opp_card_ids", [])
            if opp_card_ids:
                archetype = classify_opponent_deck(opp_card_ids, fmt)
                if archetype != "Unknown":
                    with get_connection() as conn:
                        conn.execute(
                            "UPDATE match_log SET opp_deck = ? WHERE id = ?",
                            (archetype, row["id"])
                        )
                    updated += 1
                    print(f"  Match {arena_id[:12]}... -> {archetype}")

    print(f"Updated {updated}/{len(rows)} matches with opponent deck classification.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse MTGA logs for match data")
    parser.add_argument("--all", action="store_true",
                        help="Parse both Player.log and Player-prev.log")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show matches without saving to DB")
    parser.add_argument("--resolve-cards", action="store_true",
                        help="Resolve Arena card IDs to names via Scryfall")
    parser.add_argument("--summary", action="store_true",
                        help="Print match summary")
    parser.add_argument("--knowledge-block", action="store_true",
                        help="Generate harness knowledge block")
    parser.add_argument("--format", default="standard",
                        help="Format to tag matches with (default: standard)")
    parser.add_argument("--deck", default="",
                        help="Your deck archetype name")
    parser.add_argument("--log", default=None,
                        help="Custom log file path")
    parser.add_argument("--classify-opponents", action="store_true",
                        help="Re-classify opponent decks for match_log entries with empty opp_deck")
    args = parser.parse_args()

    # Re-classify existing matches with empty opp_deck
    if args.classify_opponents:
        _reclassify_opponent_decks(args.format)
        return

    # Parse logs
    all_matches = []

    if args.log:
        print(f"Parsing: {args.log}")
        all_matches.extend(parse_log_file(args.log))
    else:
        print(f"Parsing: {PLAYER_LOG}")
        all_matches.extend(parse_log_file(PLAYER_LOG))
        if args.all:
            print(f"Parsing: {PLAYER_PREV_LOG}")
            all_matches.extend(parse_log_file(PLAYER_PREV_LOG))

    # Deduplicate across files (same match_id could appear in both)
    seen = set()
    unique = []
    for m in all_matches:
        if m["match_id"] not in seen:
            seen.add(m["match_id"])
            unique.append(m)
    all_matches = sorted(unique, key=lambda m: m["date"])

    print(f"Found {len(all_matches)} complete matches")

    # Resolve card IDs
    card_map = None
    if args.resolve_cards and all_matches:
        all_card_ids = []
        for m in all_matches:
            all_card_ids.extend(m["deck_card_ids"])
            all_card_ids.extend(m["sideboard_card_ids"])
        if all_card_ids:
            card_map = resolve_card_ids(all_card_ids)

    # Summary
    if args.summary or args.dry_run:
        print_summary(all_matches, card_map)

    # Knowledge block
    if args.knowledge_block:
        block = generate_knowledge_block(all_matches, card_map)
        if block:
            print("\n--- Knowledge Block ---")
            print(block)

    # Save to DB
    if not args.dry_run and all_matches:
        saved = save_matches_to_db(all_matches, args.format, args.deck)
        print(f"Saved {saved} new matches to match_log ({len(all_matches) - saved} already existed)")
    elif not all_matches:
        print("No matches to save.")


if __name__ == "__main__":
    main()
