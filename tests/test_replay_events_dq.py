"""M1 data-quality fix tests for analysis.replay_events.

Covers the two confirmed defects (see
docs/superpowers/specs/2026-06-09-replay-viewer-m1-data-quality-design.md):

  Bug 1 — event multiplication / non-monotonic game_num caused by
          appending the same match twice (cross-file + in-file GSM resends).
  Bug 2 — sparse hand/library/GY/exile because a Diff's partial zones[] is
          treated as the full state, wrongly wiping unreported zones.

Plus the cache schema gate and serve-stale-on-rebuild-miss behavior.
"""
from __future__ import annotations

import json

import pytest

from analysis import replay_events
from tests.fixtures.replay_events import (
    make_blob_iter, make_blob_iter_both_files, client_mulligan,
    match_start, match_end, game_state,
)


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(replay_events, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(replay_events, "transcript_cache_path",
                        lambda mid: tmp_path / f"{mid}.json")
    monkeypatch.setattr(replay_events, "_load_grpid_names", lambda _p: {})
    return tmp_path


def _game_num_sequence(events):
    seq, prev = [], object()
    for e in events:
        g = e.get("game_num")
        if g != prev:
            seq.append(g)
            prev = g
    return seq


# ── Bug 1: duplication ────────────────────────────────────────────────

def test_duplication_across_two_logs_does_not_multiply(monkeypatch):
    """A match present in BOTH log files yields the same stream as one file."""
    MID = "dq-dup-001"
    blobs = [
        match_start(MID),
        client_mulligan("MulliganOption_AcceptHand", transaction_id="tx-keep-1"),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1",
                   game_state_id=10, life=(20, 20)),
        game_state(game_num=1, turn_num=1, phase="Phase_Combat",
                   game_state_id=11, life=(20, 17)),
        game_state(game_num=2, turn_num=1, phase="Phase_Main1",
                   game_state_id=10, life=(20, 20)),
        match_end(MID),
    ]
    # Baseline: single file.
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter(blobs))
    single = replay_events.build_event_stream(MID, force_refresh=True)

    # Same match in both Player.log and Player-prev.log.
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter_both_files(blobs))
    both = replay_events.build_event_stream(MID, force_refresh=True)

    assert len(both["events"]) == len(single["events"])
    assert _game_num_sequence(both["events"]) == _game_num_sequence(single["events"])
    keep_single = sum(1 for e in single["events"] if e["kind"] == "keep_hand")
    keep_both = sum(1 for e in both["events"] if e["kind"] == "keep_hand")
    assert keep_both == keep_single == 1


def test_in_file_gsm_resend_is_deduped(monkeypatch):
    """A GSM resent under the same (game_num, gameStateId) is processed once."""
    MID = "dq-resend-001"
    blobs = [
        match_start(MID),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=50),
        game_state(game_num=1, turn_num=1, phase="Phase_Main2", game_state_id=51),
        # Resend of gsid=50 (Arena retransmits an earlier snapshot).
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=50),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter(blobs))
    result = replay_events.build_event_stream(MID, force_refresh=True)
    phase_changes = [e for e in result["events"] if e["kind"] == "phase_change"]
    # Main1 -> Main2 only; the resend of gsid=50 must NOT add a third.
    assert len(phase_changes) == 2


def test_cross_game_gsid_reuse_is_not_deduped(monkeypatch):
    """gameStateId resets each game, so (g1,1) and (g2,1) are distinct states."""
    MID = "dq-reuse-001"
    blobs = [
        match_start(MID),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=1),
        game_state(game_num=2, turn_num=1, phase="Phase_Main2", game_state_id=1),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter(blobs))
    result = replay_events.build_event_stream(MID, force_refresh=True)
    phase_changes = [e for e in result["events"] if e["kind"] == "phase_change"]
    assert len(phase_changes) == 2
    assert 1 in _game_num_sequence(result["events"])
    assert 2 in _game_num_sequence(result["events"])


def test_client_message_transaction_id_is_deduped(monkeypatch):
    """Two MulliganResp blobs sharing a transactionId produce one event."""
    MID = "dq-tx-001"
    blobs = [
        match_start(MID),
        client_mulligan("MulliganOption_Mulligan", transaction_id="tx-A"),
        client_mulligan("MulliganOption_Mulligan", transaction_id="tx-A"),  # resend
        client_mulligan("MulliganOption_AcceptHand", transaction_id="tx-B"),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=5),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter(blobs))
    result = replay_events.build_event_stream(MID, force_refresh=True)
    mulls = [e for e in result["events"] if e["kind"] == "mulligan_decision"]
    keeps = [e for e in result["events"] if e["kind"] == "keep_hand"]
    assert len(mulls) == 1   # the resend of tx-A collapses
    assert len(keeps) == 1


def test_mulligan_to_n_correct_after_duplication(monkeypatch):
    """key_events mulligan_to_N is computed from the de-duplicated count."""
    MID = "dq-mullkey-001"
    blobs = [
        match_start(MID),
        client_mulligan("MulliganOption_Mulligan", transaction_id="tx-1"),
        client_mulligan("MulliganOption_AcceptHand", transaction_id="tx-2"),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=9),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs",
                        make_blob_iter_both_files(blobs))   # duplicated
    result = replay_events.build_event_stream(MID, force_refresh=True)
    keys = result["match_meta"]["key_events_by_turn"]
    mull_keys = [k for k in keys if k["kind"].startswith("mulligan_to_")]
    assert len(mull_keys) == 1
    assert mull_keys[0]["kind"] == "mulligan_to_6"


def test_other_matches_events_are_excluded(monkeypatch):
    """GSMs/client messages from a DIFFERENT match in the same log are not
    mixed into the target match's stream."""
    OTHER = "other-match-xyz"
    TARGET = "target-match-abc"
    blobs = [
        # A different match, fully bracketed, with a kept hand and a life swing.
        match_start(OTHER),
        client_mulligan("MulliganOption_AcceptHand", transaction_id="other-tx"),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1",
                   game_state_id=1, life=(20, 15)),
        match_end(OTHER),
        # The target match: one quiet game state, no mulligan, no life change.
        match_start(TARGET),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1",
                   game_state_id=1, life=(20, 20)),
        match_end(TARGET),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter(blobs))
    result = replay_events.build_event_stream(TARGET, force_refresh=True)
    kinds = [e["kind"] for e in result["events"]]
    assert kinds.count("keep_hand") == 0, "other match's kept hand leaked in"
    assert kinds.count("life_change") == 0, "other match's life total leaked in"
    assert all(e["game_num"] == 1 for e in result["events"])


# ── Bug 2: diff-aware zone tracking ───────────────────────────────────

def test_diff_only_reporting_hand_preserves_battlefield(monkeypatch):
    """A later GSM reporting only Hand must not wipe battlefield instances."""
    MID = "dq-zone-001"
    grpids = {700: "Llanowar Elves", 800: "Forest"}
    objs = [
        {"instanceId": 1, "grpId": 700, "ownerSeatId": 1, "controllerSeatId": 1},
        {"instanceId": 2, "grpId": 800, "ownerSeatId": 1, "controllerSeatId": 1},
    ]
    blobs = [
        match_start(MID),
        # Full-ish: battlefield has inst 1, hand has inst 2, library reported.
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=20,
                   game_objects=objs,
                   zones=[
                       {"type": "ZoneType_Battlefield", "objectInstanceIds": [1]},
                       {"type": "ZoneType_Hand", "objectInstanceIds": [2]},
                       {"type": "ZoneType_Library", "objectInstanceIds": []},
                   ]),
        # Diff: ONLY Hand is reported (inst 2 played out of hand). No battlefield.
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=21,
                   game_objects=objs,
                   zones=[
                       {"type": "ZoneType_Hand", "objectInstanceIds": []},
                   ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter(blobs))
    monkeypatch.setattr(replay_events, "_load_grpid_names", lambda _p: grpids)
    result = replay_events.build_event_stream(MID, force_refresh=True)
    last_seq = result["events"][-1]["seq"]
    board = replay_events.replay_board_at(result["events"], last_seq)
    bf_ids = [c["instance_id"] for c in board["you"]["battlefield"]]
    assert 1 in bf_ids, "battlefield instance wiped by an unrelated Hand diff"
    assert board["you"]["hand_count"] == 0


def test_hidden_library_attributed_by_zone_owner(monkeypatch):
    """Hidden zone cards (not in gameObjects) are attributed via the zone's
    ownerSeatId so library/hand counts are correct for both players."""
    MID = "dq-lib-001"
    blobs = [
        match_start(MID),
        game_state(game_num=1, turn_num=1, phase="Phase_Main1", game_state_id=5,
                   game_objects=[],  # hidden cards: no gameObjects entries
                   zones=[
                       {"type": "ZoneType_Library", "ownerSeatId": 1,
                        "objectInstanceIds": [101, 102, 103]},
                       {"type": "ZoneType_Library", "ownerSeatId": 2,
                        "objectInstanceIds": [201, 202]},
                   ]),
        match_end(MID),
    ]
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter(blobs))
    result = replay_events.build_event_stream(MID, force_refresh=True)
    board = replay_events.replay_board_at(result["events"],
                                          result["events"][-1]["seq"])
    assert board["you"]["library_count"] == 3
    assert board["opp"]["library_count"] == 2


# ── Cache schema gate + serve-stale ───────────────────────────────────

def test_schema_gate_triggers_rebuild(tmp_path, monkeypatch):
    """A cache at an older schema_version is rebuilt even if capabilities pass."""
    MID = "dq-schema-001"
    stale = {
        "arena_match_id": MID,
        "schema_version": 1,
        "capabilities": dict(replay_events.M1_CAPABILITIES),
        "match_meta": {"games": [], "key_events_by_turn": []},
        "events": [{"seq": 0, "kind": "phase_change", "turn_num": 1, "game_num": 1}],
        "my_seat": 1, "opp_seat": 2, "opp_name": "Old",
    }
    (tmp_path / f"{MID}.json").write_text(json.dumps(stale), encoding="utf-8")

    called = {"n": 0}
    def _spy(_p):
        called["n"] += 1
        for b in [match_start(MID),
                  game_state(game_num=1, turn_num=1, game_state_id=1),
                  match_end(MID)]:
            yield b
    monkeypatch.setattr(replay_events, "_iter_json_blobs", _spy)
    result = replay_events.build_event_stream(MID, force_refresh=False)
    assert called["n"] > 0, "old-schema cache should have triggered a rebuild"
    assert result["schema_version"] == replay_events.SCHEMA_VERSION


def test_serve_stale_when_match_absent_from_logs(tmp_path, monkeypatch):
    """Old-schema cache + match no longer in logs -> serve the stale cache, not None."""
    MID = "dq-stale-001"
    stale = {
        "arena_match_id": MID,
        "schema_version": 1,
        "capabilities": dict(replay_events.M1_CAPABILITIES),
        "match_meta": {"games": [], "key_events_by_turn": []},
        "events": [{"seq": 0, "kind": "phase_change", "turn_num": 1, "game_num": 1}],
        "my_seat": 1, "opp_seat": 2, "opp_name": "Old",
    }
    (tmp_path / f"{MID}.json").write_text(json.dumps(stale), encoding="utf-8")
    # Logs are empty -> match not found on rebuild.
    monkeypatch.setattr(replay_events, "_iter_json_blobs", make_blob_iter([]))
    result = replay_events.build_event_stream(MID, force_refresh=False)
    assert result is not None
    assert result["events"][0]["kind"] == "phase_change"
    assert result["opp_name"] == "Old"
