"""MTGO local game-log parser.

Fixtures are SYNTHETIC (this repo is public): .dat bytes are built here in the
exact on-disk layout MTGO writes, with made-up player names. The real-corpus
test at the bottom reads the gitignored raw snapshot and skips when absent.
"""
import struct
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scrapers import mtgo_log_parser as p

GUID = "11111111-2222-3333-4444-555555555555"
T0 = datetime(2026, 1, 16, 23, 4, 11)


def _str(s: str) -> bytes:
    raw = s.encode("utf-8")
    n, out = len(raw), bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out) + raw


def _ticks(dt: datetime) -> bytes:
    return struct.pack("<q", int((dt - datetime(1, 1, 1)) / timedelta(microseconds=1)) * 10)


def build_dat(messages, token=GUID, author=""):
    out = b"\x01\x00" + _str(token) + b"\x04\x00" + _str(token)
    for k, m in enumerate(messages):
        out += _ticks(T0 + timedelta(seconds=k)) + _str(author) + _str(m)
    return out


def card(name, cat, obj):
    return f"@[{name}@:{cat},{obj}:@]"


GAME1 = [
    "@PAlice rolled a 6.", "@PBob rolled a 2.",
    "@P@PAlice joined the game.", "@P@PBob joined the game.",
    "@PAlice chooses to play first.",
    "@PAlice begins the game with seven cards in hand.",
    "@PBob mulligans to six cards.",
    "@PBob puts a card on the bottom of their library and begins the game with six cards in hand.",
    "@PTurn 1: Alice",
    f"@PAlice plays {card('Island', 171776, 435)}.",
    "@PTurn 1: Bob",
    f"@PBob plays {card('Arid Mesa', 181738, 476)}.",
    f"@PBob casts {card('Guide of Souls', 251350, 433)}.",
    "@PTurn 2: Alice",
    f"@PAlice casts {card('Counterspell', 105654, 442)} targeting {card('Voice of Victory', 278022, 441)}.",
    "@PTurn 2: Bob",
    f"@PBob casts {card('Guide of Souls', 251350, 449)}.",
    "@PBob has conceded from the game.",
    "@PAlice wins the game.",
    "@PAlice leads the match 1-0",
]
GAME2 = [
    "@P@PBob joined the game.", "@P@PAlice joined the game.",
    "@PBob chooses to play first.",
    "@PAlice begins the game with seven cards in hand.",
    "@PBob begins the game with seven cards in hand.",
    "@PTurn 1: Bob",
    f"@PBob plays {card('Mountain', 219580, 500)}.",
    "@PTurn 3: Alice",
    "@PBob wins the game.",
    "Match Tied 1-1",
]
GAME3 = [
    "@P@PAlice joined the game.", "@P@PBob joined the game.",
    "@PAlice chooses to draw first.",
    "@PAlice begins the game with seven cards in hand.",
    "@PBob begins the game with seven cards in hand.",
    "@PTurn 4: Bob",
    "@PBob has left the game.",
    "@PAlice wins the match 2-1",
]


# ---------------------------------------------------------------- binary layer

def test_read_gamelog_roundtrip():
    log = p.read_gamelog(build_dat(GAME1))
    assert log.token == GUID
    assert [m for _, m in log.entries] == GAME1
    assert log.entries[0][0] == T0
    assert log.decode_errors == 0


def test_read_gamelog_old_format_with_author_and_numeric_id():
    log = p.read_gamelog(build_dat(GAME1[:3], token="882340986", author="Alice"))
    assert log.token == "882340986"
    assert [m for _, m in log.entries] == GAME1[:3]


def test_read_gamelog_empty_match():
    log = p.read_gamelog(build_dat([]))
    assert log.entries == [] and log.decode_errors == 0


def test_read_gamelog_truncated_tail_is_counted_not_raised():
    data = build_dat(GAME1)[:-5]
    log = p.read_gamelog(data)
    assert log.decode_errors == 1
    assert len(log.entries) == len(GAME1) - 1


def test_read_gamelog_bad_utf8_falls_back_without_error():
    data = build_dat(["x"]).replace(_str("x"), bytes([3]) + b"L\xf3r")
    log = p.read_gamelog(data)
    assert log.entries[0][1] == "Lór"
    assert log.decode_errors == 0


# ---------------------------------------------------------------- match layer

@pytest.fixture
def match():
    log = p.read_gamelog(build_dat(GAME1 + GAME2 + GAME3))
    return p.parse_match(log, local_player="Alice")


def test_players_and_sides(match):
    assert match["players"] == ["Alice", "Bob"]
    assert match["local"] == "Alice" and match["opponent"] == "Bob"
    assert match["spectated"] is False


def test_games_split(match):
    assert len(match["games"]) == 3


def test_game_winners_and_end_reasons(match):
    g1, g2, g3 = match["games"]
    assert (g1["winner"], g1["end_reason"]) == ("Alice", "concede")
    assert (g2["winner"], g2["end_reason"]) == ("Bob", "win")
    # left the game + no wins-the-game line: winner only from the score line
    assert (g3["winner"], g3["end_reason"]) == ("Alice", "score")


def test_play_draw(match):
    g1, g2, g3 = match["games"]
    assert g1["on_play"] == "Alice"
    assert g2["on_play"] == "Bob"
    assert g3["on_play"] == "Bob"  # Alice chose to DRAW


def test_mulligans_and_turns(match):
    g1 = match["games"][0]
    assert g1["hand_size"] == {"Alice": 7, "Bob": 6}
    assert g1["turns"] == 2
    assert match["games"][2]["turns"] == 4


def test_turn_marker_is_not_a_player(match):
    assert "Turn" not in match["players"]


def test_cards_seen_keyed_by_catalog_id(match):
    g1 = match["games"][0]
    assert g1["cards"]["Bob"] == {181738: 1, 251350: 2}
    # targets are not attributed to the caster
    assert g1["cards"]["Alice"] == {171776: 1, 105654: 1}
    assert match["card_names"][251350] == "Guide of Souls"


def test_match_score_and_cross_check(match):
    assert match["score"] == {"Alice": 2, "Bob": 1}
    assert match["result"] == "win"
    assert match["score_check"] == "ok"


def test_score_check_flags_disagreement():
    bad = GAME1[:-3] + ["@PAlice has conceded from the game.", "@PBob wins the game.",
                        "@PAlice leads the match 1-0"]
    m = p.parse_match(p.read_gamelog(build_dat(bad)), local_player="Alice")
    assert m["score_check"] == "mismatch"


def test_no_score_line_is_reported_not_guessed():
    m = p.parse_match(p.read_gamelog(build_dat(GAME1[:-1])), local_player="Alice")
    assert m["score"] is None
    assert m["score_check"] == "no_score_line"
    # 1-0 with no match-end line: the match may not have finished
    assert m["result"] == "incomplete"


def test_log_that_stops_mid_match_is_incomplete_not_draw():
    unfinished = GAME1 + GAME2 + GAME3[:5]
    m = p.parse_match(p.read_gamelog(build_dat(unfinished)), local_player="Alice")
    assert m["score"] == {"Alice": 1, "Bob": 1}
    assert m["games"][2]["end_reason"] == "unknown"
    assert m["result"] == "incomplete"


def test_two_game_wins_decide_match_without_match_line():
    msgs = GAME1[:-1] + ["@PAlice leads the match 1-0"] + GAME1[2:-1]
    m = p.parse_match(p.read_gamelog(build_dat(msgs)), local_player="Alice")
    assert [g["winner"] for g in m["games"]] == ["Alice", "Alice"]
    assert m["result"] == "win"


def test_game_without_opening_lines_is_still_counted():
    # log begins mid-game: no roll / choice / opening hand
    msgs = ["@PBob has conceded from the game.", "@PAlice wins the game.",
            "@PBob has lost connection to the game.", "@PAlice leads the match 1-0"]
    m = p.parse_match(p.read_gamelog(build_dat(msgs)), local_player="Alice")
    assert [g["winner"] for g in m["games"]] == ["Alice"]
    assert m["score_check"] == "ok"


def test_match_line_before_game_line_does_not_invent_a_game():
    msgs = GAME1 + ["@PBob chooses to play first.", "@PBob has conceded from the game.",
                    "@PAlice wins the match 2-0", "@PAlice wins the game."]
    m = p.parse_match(p.read_gamelog(build_dat(msgs)), local_player="Alice")
    assert [g["winner"] for g in m["games"]] == ["Alice", "Alice"]
    assert m["score_check"] == "ok"


def test_loses_the_game_line():
    msgs = GAME1[:-3] + ["@PBob loses the game.", "@PAlice leads the match 1-0"]
    m = p.parse_match(p.read_gamelog(build_dat(msgs)), local_player="Alice")
    assert (m["games"][0]["winner"], m["games"][0]["end_reason"]) == ("Alice", "loss")


def test_game_awarded_after_opponent_leaves_between_games():
    msgs = GAME1 + ["@PBob has left the game.", "@PAlice wins the game.",
                    "@PAlice wins the match 2-0"]
    m = p.parse_match(p.read_gamelog(build_dat(msgs)), local_player="Alice")
    assert [g["winner"] for g in m["games"]] == ["Alice", "Alice"]
    assert m["score_check"] == "ok"
    assert m["result"] == "win"


def test_spectated_match():
    m = p.parse_match(p.read_gamelog(build_dat(GAME1)), local_player="Carol")
    assert m["spectated"] is True
    assert m["result"] is None


def test_local_player_fallback_most_frequent():
    logs = [p.read_gamelog(build_dat(GAME1)), p.read_gamelog(build_dat(GAME2))]
    assert p.guess_local_player(logs) in {"Alice", "Bob"}
    logs.append(p.read_gamelog(build_dat(
        [s.replace("Bob", "Dan") for s in GAME1])))
    assert p.guess_local_player(logs) == "Alice"


# ---------------------------------------------------------------- text log + card data

def test_parse_text_log(tmp_path):
    f = tmp_path / "mtgo.log"
    f.write_text(
        "09:28:08 [INF] (Twitch Info|Username: Alice Deck Used in Game ID: 42) "
        '[{"CatalogId":54200,"Quantity":3,"Annotation":"NotSet","InSideboard":false},'
        '{"CatalogId":130215,"Quantity":1,"Annotation":"NotSet","InSideboard":true}]\n'
        "09:28:09 [INF] (Game Management|x) Message: {\"MatchCreateInfo\":"
        '{"MatchToken":"' + GUID + '","MatchID":7,"MatchParentEventType":2,'
        '"MatchTypeCd":"BES","GameStructureCd":"CMODERN","PlayerFormatCd":"D1V1"}}\n'
        "09:28:10 [INF] (Twitch Info|Game Play Status Update for Game ID: 42, "
        'Match ID: 7, Event ID: 7) {"Players":[],"Cards":[]}\n',
        encoding="utf-8")
    t = p.parse_text_log(f)
    assert t["username"] == "Alice"
    assert t["decks"][42] == {"main": {54200: 3}, "side": {130215: 1}}
    assert t["game_to_token"][42] == GUID
    assert t["match_formats"][GUID] == "modern"
    assert t["frames"] == 1


def test_load_card_names_two_id_spaces(tmp_path):
    (tmp_path / "CARDNAME_STRING.xml").write_text(
        '<?xml version="1.0"?><CARDNAME_STRING_ITEMS>'
        '<CARDNAME_STRING_ITEM id="ID1027_9">Guide of Souls</CARDNAME_STRING_ITEM>'
        '<CARDNAME_STRING_ITEM id="ID1027_10">L&#243;rien Revealed</CARDNAME_STRING_ITEM>'
        "</CARDNAME_STRING_ITEMS>", encoding="utf-8")
    (tmp_path / "client_MH3.xml").write_text(
        '<CardSet id="MH3"><DigitalObject DigitalObjectCatalogID="DOC_128001">'
        '<CARDNAME_STRING id="ID1027_9"/><CARDTEXTURE_NUMBER value="251350"/>'
        '</DigitalObject>'
        '<DigitalObject DigitalObjectCatalogID="DOC_224060">'
        '<CARDNAME_STRING id="ID1027_10"/></DigitalObject></CardSet>', encoding="utf-8")
    names = p.load_card_names(tmp_path)
    assert names["catalog"] == {128001: "Guide of Souls", 224060: "Lórien Revealed"}
    assert names["texture"] == {251350: "Guide of Souls"}


# ---------------------------------------------------------------- real corpus (local only)

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "mtgo"


@pytest.mark.skipif(not any(RAW.glob("*/Match_GameLog_*.dat")), reason="no local MTGO snapshot")
def test_real_corpus_gates():
    report = p.corpus_report(sorted(RAW.glob("*/Match_GameLog_*.dat")))
    assert report["parse_rate"] >= 0.99, report["failures"]
    assert report["score_agreement"] >= 0.95, report["mismatches"][:5]


# ---------------------------------------------------------------- NRBF + game history

from scrapers import nrbf  # noqa: E402


def _nrbf_obj():
    """SerializedStreamHeader + BinaryLibrary + ClassWithMembersAndTypes
    {Name: string, Wins: int32, Start: DateTime, Opp: List<string> ref}
    + the referenced ArraySingleString + MessageEnd."""
    b = bytearray()
    b += bytes([0]) + struct.pack("<iiii", 1, -1, 1, 0)
    b += bytes([12]) + struct.pack("<i", 2) + _str("Lib")
    b += bytes([5]) + struct.pack("<i", 1) + _str("Demo.Match")
    b += struct.pack("<i", 4) + _str("Name") + _str("Wins") + _str("Start") + _str("Opp")
    b += bytes([1, 0, 0, 6])            # String, Primitive, Primitive, StringArray
    b += bytes([8, 13])                 # Int32, DateTime
    b += struct.pack("<i", 2)           # library id
    b += bytes([6]) + struct.pack("<i", 3) + _str("Zed")
    b += struct.pack("<i", 2)
    b += _ticks(T0)[:8]
    b += bytes([9]) + struct.pack("<i", 4)
    b += bytes([17]) + struct.pack("<ii", 4, 3)
    b += bytes([6]) + struct.pack("<i", 5) + _str("Bob")
    b += bytes([13, 1])                 # one null
    b += bytes([9]) + struct.pack("<i", 3)  # reference back to "Zed"
    b += bytes([11])
    return bytes(b)


def test_nrbf_reads_object_graph():
    obj = nrbf.loads(_nrbf_obj())
    assert obj["__class__"] == "Demo.Match"
    assert obj["Name"] == "Zed" and obj["Wins"] == 2
    assert obj["Start"] == T0
    assert obj["Opp"] == ["Bob", None, "Zed"]


def _hist_root(items):
    return {"__class__": "List", "_items": items + [None], "_size": len(items)}


def _hmatch(mid, opp, start, gw, gl, winner, loser, game_ids, code="CMODERN", desc=""):
    L = lambda xs: {"_items": xs, "_size": len(xs)}  # noqa: E731
    return {"__class__": "X.History.HistoricalMatch", "Id": mid, "StartTime": start,
            "Opponents": L([opp]), "GameWins": gw, "GameLosses": gl,
            "MatchWinners": L([winner] if winner else []),
            "MatchLosers": L([loser] if loser else []),
            "GameIds": L(game_ids + [0]), "Description": desc, "Round": 0,
            "GameStructure": {"GameStructureCd": code}}


def test_flatten_history_tournament_and_standalone():
    child = _hmatch(7, "Bob", T0, 2, 1, "Alice", "Bob", [42, 43, 44], desc="Tournament:9 Round:3")
    child["Round"] = 3
    tourn = {"__class__": "X.History.HistoricalTournament", "Id": 9,
             "Description": "Modern Challenge 32",
             "Matches": {"_items": [child], "_size": 1}}
    solo = _hmatch(8, "Dan", T0, 0, 2, "Dan", "Alice", [50, 51], code="CPIONEER")
    hist = p.flatten_history(_hist_root([tourn, solo]))
    assert [h["id"] for h in hist] == [7, 8]
    assert hist[0]["event"] == "Modern Challenge 32" and hist[0]["round"] == 3
    assert hist[0]["format"] == "modern" and hist[1]["format"] == "pioneer"
    assert hist[0]["game_ids"] == [42, 43, 44]
    assert p.history_result(hist[0], "Alice") == "win"
    assert p.history_result(hist[1], "Alice") == "loss"


def test_link_history_by_opponent_and_time_and_by_game_id():
    hist = p.flatten_history(_hist_root([
        _hmatch(1, "Bob", T0 - timedelta(hours=3), 2, 0, "Alice", "Bob", [10, 11]),
        _hmatch(2, "Bob", T0 + timedelta(minutes=2), 1, 2, "Bob", "Alice", [20, 21, 22]),
    ]))
    m = p.parse_match(p.read_gamelog(build_dat(GAME1)), local_player="Alice")
    assert p.link_history(m, hist)["id"] == 2
    old = p.parse_match(p.read_gamelog(build_dat(GAME1, token="11")), local_player="Alice")
    assert p.link_history(old, hist)["id"] == 1
    far = dict(m, started_at=T0 + timedelta(days=1))
    assert p.link_history(far, hist) is None
