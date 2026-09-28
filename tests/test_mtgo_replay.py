"""MTGO -> replay event stream. Synthetic data only (public repo)."""
import json
from datetime import timedelta

from analysis import mtgo_replay as mr
from analysis.replay_events import replay_board_at
from scrapers import mtgo_log_parser as p
from tests.test_mtgo_log_parser import GAME1, T0, build_dat

NAMES = {"texture": {251350: "Guide of Souls", 171776: "Island"},
         "catalog": {10: "Guide of Souls", 11: "Island", 12: "Counterspell", 13: "Arid Mesa",
                     14: "Sideboard Card"}}


def _frame_line(t, players, cards, gid=42):
    return (f"{t:%H:%M:%S} [INF] (Twitch Info|Game Play Status Update for Game ID: {gid}, "
            f"Match ID: 7, Event ID: 7) " + json.dumps({"Players": players, "Cards": cards}) + "\n")


def _players(life_a=20, life_b=20, hand_a=7, hand_b=6):
    return [{"Id": 0, "Name": "Alice", "Life": life_a, "HandCount": hand_a, "LibraryCount": 53},
            {"Id": 1, "Name": "Bob", "Life": life_b, "HandCount": hand_b, "LibraryCount": 54}]


def _log_file(tmp_path):
    t = T0 + timedelta(seconds=9)                     # around "Alice plays Island"
    f1 = [{"Id": 435, "CatalogID": 11, "Zone": "Hand", "Owner": 0, "Controller": 0},
          {"Id": 900, "CatalogID": 14, "Zone": "Sideboard", "Owner": 0, "Controller": 0}]
    f2 = [{"Id": 435, "CatalogID": 11, "Zone": "Battlefield", "Owner": 0, "Controller": 0},
          {"Id": 476, "CatalogID": 13, "Zone": "Battlefield", "Owner": 1, "Controller": 1},
          {"Id": 900, "CatalogID": 14, "Zone": "Sideboard", "Owner": 0, "Controller": 0}]
    f3 = [c for c in f2 if c["Id"] != 476] + [
          {"Id": 476, "CatalogID": 13, "Zone": "Graveyard", "Owner": 1, "Controller": 1}]
    lines = [_frame_line(t, _players(), f1), _frame_line(t, _players(), f1),        # repeat dropped
             _frame_line(t + timedelta(seconds=2), _players(hand_a=6), f2),
             _frame_line(t + timedelta(seconds=5), _players(life_b=17, hand_a=6), f3)]
    path = tmp_path / "mtgo.log"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_load_frames_drops_repeats(tmp_path):
    frames = mr.load_frames([_log_file(tmp_path)])
    assert list(frames) == [42] and len(frames[42]) == 3


def test_frame_diff_moves_appearances_and_ignores_sideboard():
    prev = {}
    d1, prev = mr.frame_diff(prev, [{"Id": 1, "CatalogID": 10, "Zone": "Hand", "Controller": 0},
                                    {"Id": 2, "CatalogID": 14, "Zone": "Sideboard", "Controller": 0}],
                             0, NAMES["catalog"])
    assert [(d["instance_id"], d["to"], d["controller"], d["grpid"]) for d in d1] == [(1, "hand", "you", None)]
    d2, prev = mr.frame_diff(prev, [{"Id": 1, "CatalogID": 10, "Zone": "Battlefield", "Controller": 0}],
                             0, NAMES["catalog"])
    assert (d2[0]["from"], d2[0]["to"], d2[0]["card"]) == ("hand", "battlefield", "Guide of Souls")
    d3, prev = mr.frame_diff(prev, [], 0, NAMES["catalog"])
    assert d3[0]["to"] is None


def test_stream_merges_text_and_board_and_hides_opp_hand(tmp_path):
    log = p.read_gamelog(build_dat(GAME1))
    frames = mr.load_frames([_log_file(tmp_path)])
    s = mr.build_stream(log, "Alice", frames, NAMES)
    assert s["capabilities"]["board"] is True and s["my_seat"] == 0 and s["opp_name"] == "Bob"
    ev = s["events"]
    assert [e["seq"] for e in ev] == list(range(len(ev)))
    kinds = {e["kind"] for e in ev}
    assert {"play_land", "cast_spell", "zone_change", "game_end"} <= kinds
    casts = [e for e in ev if e["kind"] == "cast_spell"]
    assert casts[0]["card_name"] == "Guide of Souls" and casts[0]["actor_seat"] == 1
    assert casts[0]["turn_num"] == 1
    board = replay_board_at(ev, ev[-1]["seq"])
    assert [c["name"] for c in board["you"]["battlefield"]] == ["Island"]
    assert [c["name"] for c in board["opp"]["graveyard"]] == ["Arid Mesa"]
    assert board["you"]["hand_count"] == 6 and board["opp"]["hand_count"] == 6   # counts from MTGO
    assert board["opp"]["hand"] == []                                             # never listed
    assert ev[-1]["life_after"] == {"you": 20, "opp": 17}


def test_first_frame_shows_your_hand(tmp_path):
    s = mr.build_stream(p.read_gamelog(build_dat(GAME1)), "Alice",
                        mr.load_frames([_log_file(tmp_path)]), NAMES)
    first_board = next(e for e in s["events"] if e["kind"] == "zone_change")
    b = replay_board_at(s["events"], first_board["seq"])
    assert [c["name"] for c in b["you"]["hand"]] == ["Island"]


def test_match_without_frames_is_play_by_play_only():
    s = mr.build_stream(p.read_gamelog(build_dat(GAME1)), "Alice", {}, NAMES)
    assert s["capabilities"]["board"] is False
    assert all(not e["board_diff"] for e in s["events"])
    assert any(e["details"]["text"] == "Alice chooses to play first." for e in s["events"])


def test_frames_of_other_players_or_times_are_ignored(tmp_path):
    frames = mr.load_frames([_log_file(tmp_path)])
    frames[99] = [(3, 0, 0, _players(), [])]                   # same players, hours away
    frames[98] = [(T0.hour, T0.minute, T0.second,
                   [{"Id": 0, "Name": "Carol"}, {"Id": 1, "Name": "Dan"}], [])]
    log = p.read_gamelog(build_dat(GAME1))
    assert mr.games_for_match(frames, {"Alice", "Bob"}, log.entries[0][0], log.entries[-1][0]) == [42]


def test_seat_ids_swap_between_games_but_you_stay_you(tmp_path):
    """MTGO reassigns Player Ids per game; a card in YOUR hand must stay yours."""
    t = T0 + timedelta(seconds=9)
    swapped = [{"Id": 1, "Name": "Alice", "Life": 20, "HandCount": 1, "LibraryCount": 53},
               {"Id": 0, "Name": "Bob", "Life": 20, "HandCount": 7, "LibraryCount": 53}]
    card = [{"Id": 5, "CatalogID": 10, "Zone": "Hand", "Owner": 1, "Controller": 1}]
    (tmp_path / "a.log").write_text(_frame_line(t, _players(), [], gid=1)
                                    + _frame_line(t + timedelta(seconds=30), swapped, card, gid=2),
                                    encoding="utf-8")
    s = mr.build_stream(p.read_gamelog(build_dat(GAME1)), "Alice",
                        mr.load_frames([tmp_path / "a.log"]), NAMES)
    assert (s["my_seat"], s["opp_seat"]) == (0, 1)
    ev = s["events"]
    b = replay_board_at(ev, ev[-1]["seq"])
    assert [c["name"] for c in b["you"]["hand"]] == ["Guide of Souls"] and b["opp"]["hand"] == []
    assert ev[-1]["life_after"] == {"you": 20, "opp": 20}


def test_lines_between_games_belong_to_the_next_game():
    from tests.test_mtgo_log_parser import GAME2
    s = mr.build_stream(p.read_gamelog(build_dat(GAME1 + GAME2)), "Alice", {}, NAMES)
    games = [e["game_num"] for e in s["events"]]
    assert games == sorted(games)                       # never goes back
    joined2 = [e for e in s["events"] if e["details"]["text"] == "Bob joined the game."][-1]
    assert joined2["game_num"] == 2


def test_stray_line_after_a_game_ends_does_not_start_a_new_game():
    from tests.test_mtgo_log_parser import GAME2
    g1 = GAME1[:-1] + ["@PBob reveals @[Island@:171776,999:@]."] + GAME1[-1:]   # line between win + score
    s = mr.build_stream(p.read_gamelog(build_dat(g1 + GAME2)), "Alice", {}, NAMES)
    assert max(e["game_num"] for e in s["events"]) == 2


def test_same_session_in_two_log_copies_is_loaded_once(tmp_path):
    a = _log_file(tmp_path)
    b = tmp_path / "copy_of_live.log"
    b.write_text(a.read_text(encoding="utf-8"), encoding="utf-8")
    assert len(mr.load_frames([a, b])[42]) == 3


def test_turn_does_not_carry_into_the_next_game(tmp_path):
    from tests.test_mtgo_log_parser import GAME2
    t2 = T0 + timedelta(seconds=len(GAME1) - 1)       # game 2 frame in the SAME second as game 1's score line
    (tmp_path / "g.log").write_text(
        _frame_line(T0 + timedelta(seconds=9), _players(), [], gid=1)
        + _frame_line(t2, _players(life_a=19), [], gid=2), encoding="utf-8")
    s = mr.build_stream(p.read_gamelog(build_dat(GAME1 + GAME2)), "Alice",
                        mr.load_frames([tmp_path / "g.log"]), NAMES)
    g2_first = next(e for e in s["events"] if e["game_num"] == 2)
    assert g2_first["turn_num"] is None


def test_first_frame_life_event_is_readable(tmp_path):
    s = mr.build_stream(p.read_gamelog(build_dat(GAME1)), "Alice",
                        mr.load_frames([_log_file(tmp_path)]), NAMES)
    from gui.replay_view_model import event_summary
    assert all("None" not in event_summary(e) for e in s["events"])


def test_stale_cache_from_an_older_builder_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "_cache_path", lambda token: tmp_path / f"{token}.json")
    (tmp_path / "tok.json").write_text(json.dumps({"schema_version": "mtgo-0", "events": []}))
    calls = []
    import scrapers.mtgo_snapshot as snap
    monkeypatch.setattr(snap, "raw_root", lambda: tmp_path / "raw")
    monkeypatch.setattr(p, "discover_sources", lambda: calls.append(1) or {"appfiles": [], "logs": [], "card_data": None})
    assert mr.build_mtgo_event_stream("tok") is None and calls     # went to the sources, not the stale file
    (tmp_path / "tok.json").write_text(json.dumps({"schema_version": mr.SCHEMA, "events": [1]}))
    assert mr.build_mtgo_event_stream("tok")["events"] == [1]


def test_match_log_opens_mtgo_replay_with_notes_disabled(tmp_path, monkeypatch):
    import os
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    stream = mr.build_stream(p.read_gamelog(build_dat(GAME1)), "Alice",
                             mr.load_frames([_log_file(tmp_path)]), NAMES)
    import analysis.mtgo_replay as live
    monkeypatch.setattr(live, "build_mtgo_event_stream", lambda tok, force_refresh=False: stream)
    from db.match_log import _ensure_table
    _ensure_table()
    from gui.tabs.match_log import MatchLogTab
    tab = MatchLogTab()
    tab._open_mtgo_replay({"mtgo_match_id": GUID_T, "event_name": "League", "opp_name": "Bob",
                           "my_deck": "Boros Energy", "source": "mtgo_log"})
    win = tab._replay_windows[-1]
    end = time.time() + 5
    while time.time() < end and win._stream is None:
        app.processEvents()
        time.sleep(0.02)
    assert win._stream is stream and "League" in win.windowTitle()
    assert win._notes.isReadOnly() and not win._notes_save_btn.isEnabled()
    assert not win._mark_btn.isEnabled()
    win._persist_replay_notes()                       # must be a no-op for MTGO
    from db.database import get_connection
    with get_connection() as con:
        assert con.execute("SELECT COUNT(*) FROM match_log").fetchone()[0] == 0   # no stub row
    win.close()
    app.processEvents()
    tab.cleanup()


GUID_T = "11111111-2222-3333-4444-555555555555"
