"""Regression tests: build_event_stream must scope to ONE match.

Root cause (M1 data-quality bug, found 2026-06-16): build_event_stream
walks (PLAYER_LOG, PLAYER_PREV_LOG) and processes EVERY gameStateMessage /
clientMessage in both files -- it never scopes to `arena_match_id` (that arg
only drove seat extraction). So every replay contained all matches from both
logs mashed together: `game_num` oscillated 1->2->3->1..., the per-game
`games` list inflated, and two different matchIds produced byte-identical
output. Proven: two real matchIds both yielded events=6138, games=6.

Fix: gate event processing to the target match's start/end region, and
ignore a re-occurrence of the same match in the other rotation log.
"""
import pytest

from analysis import replay_events
from tests.fixtures.replay_events import game_state, match_end, match_start


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(replay_events, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(replay_events, "transcript_cache_path",
                        lambda mid: tmp_path / f"{mid}.json")
    monkeypatch.setattr(replay_events, "_load_grpid_names", lambda _p: {})
    return tmp_path


def _submit_deck(cards):
    """A ClientMessageType_SubmitDeckResp blob (drives match_meta['games'])."""
    return {
        "clientToMatchServiceMessageType": "ClientToMatchServiceMessageType_ClientToGREMessage",
        "payload": {
            "type": "ClientMessageType_SubmitDeckResp",
            "submitDeckResp": {"deck": {"deckCards": list(cards)}},
        },
    }


def _match_blobs(mid, n_games, opp="OppX"):
    """A complete match: start, then per game a deck submit + two phases, end."""
    seed = sum(ord(c) for c in mid)
    blobs = [match_start(mid, opp_name=opp)]
    for g in range(1, n_games + 1):
        blobs.append(_submit_deck([200 + g, 201, 202]))
        blobs.append(game_state(game_num=g, phase="Phase_Beginning",
                                step="Step_Upkeep", game_state_id=seed + 10 * g + 1))
        blobs.append(game_state(game_num=g, phase="Phase_Main1",
                                game_state_id=seed + 10 * g + 2))
    blobs.append(match_end(mid))
    return blobs


def _iter_once(blobs):
    """All blobs in Player.log; Player-prev.log empty."""
    state = {"done": False}

    def _it(_p):
        if state["done"]:
            return
        state["done"] = True
        yield from blobs
    return _it


def _iter_both(blobs):
    """Same content in BOTH rotation logs (the duplication scenario)."""
    def _it(_p):
        yield from blobs
    return _it


def _nums(stream):
    return [e["game_num"] for e in stream["events"]]


def _build(mid, iterfn, monkeypatch):
    monkeypatch.setattr(replay_events, "_iter_json_blobs", iterfn)
    return replay_events.build_event_stream(mid, force_refresh=True)


def test_single_match_baseline(monkeypatch):
    s = _build("MATCH-A", _iter_once(_match_blobs("MATCH-A", 3)), monkeypatch)
    nums = _nums(s)
    assert nums == sorted(nums), f"game_num not monotonic: {nums}"
    assert set(nums) == {1, 2, 3}
    assert len(s["match_meta"]["games"]) == 3


def test_same_match_in_both_logs_not_doubled(monkeypatch):
    blobs = _match_blobs("MATCH-A", 3)
    base = _build("MATCH-A", _iter_once(blobs), monkeypatch)
    dual = _build("MATCH-A", _iter_both(_match_blobs("MATCH-A", 3)), monkeypatch)

    nums = _nums(dual)
    assert nums == sorted(nums), f"game_num oscillated across logs: {nums}"
    assert nums == _nums(base), "dual-log doubled the event stream"
    assert len(dual["match_meta"]["games"]) == len(base["match_meta"]["games"]) == 3, \
        "dual-log doubled the per-game decklist list"


def test_stale_schema_cache_is_rebuilt(monkeypatch, tmp_path):
    """A cache written by the pre-scoping code (schema_version 1) must be
    discarded and rebuilt, not served as-is."""
    import json
    mid = "MATCH-A"
    stale = tmp_path / f"{mid}.json"
    stale.write_text(json.dumps({
        "schema_version": 1,
        "capabilities": {c: True for c in (
            "events", "board_diff", "public_info",
            "per_game_decklists", "stack_history", "log_offsets")},
        "events": [{"game_num": 99}],  # sentinel garbage
        "match_meta": {"games": []},
        "opp_name": "STALE",
    }), encoding="utf-8")

    # No force_refresh: the loader itself must reject the stale schema.
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        _iter_once(_match_blobs(mid, 3)))
    s = replay_events.build_event_stream(mid)
    assert s["schema_version"] == replay_events.SCHEMA_VERSION
    assert set(_nums(s)) == {1, 2, 3}, "stale cache was served instead of rebuilt"


def test_scopes_to_target_match_only(monkeypatch):
    """A log holding match A (3 games) + match B (1 game): building A must
    contain ONLY A's events, and building B ONLY B's."""
    log = _match_blobs("MATCH-A", 3, opp="Alice") + _match_blobs("MATCH-B", 1, opp="Bob")

    a = _build("MATCH-A", _iter_once(log), monkeypatch)
    assert set(_nums(a)) == {1, 2, 3}, f"A leaked other matches: {set(_nums(a))}"
    assert len(a["match_meta"]["games"]) == 3
    assert a["opp_name"] == "Alice"

    b = _build("MATCH-B", _iter_once(log), monkeypatch)
    assert set(_nums(b)) == {1}, f"B leaked other matches: {set(_nums(b))}"
    assert len(b["match_meta"]["games"]) == 1
    assert b["opp_name"] == "Bob"
