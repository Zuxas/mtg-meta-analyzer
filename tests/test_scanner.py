"""Tests for analysis/puzzles/scanner.py."""
import json
import pytest


def _fake_transcript(games: list[dict]) -> dict:
    return {"match_id": "fake-match-1", "games": games}


def _turn(turn_num: int, actions: list[str], active_seat: int = 1) -> dict:
    return {"turn": turn_num, "active_seat": active_seat, "actions": actions}


def test_candidate_dataclass_fields():
    from analysis.puzzles.scanner import Candidate
    c = Candidate(
        arena_match_id="m-1", game_num=1, turn_num=5,
        category="stabilize", heuristic_score=0.42, evidence="test",
    )
    assert c.arena_match_id == "m-1"
    assert c.category == "stabilize"
    assert c.heuristic_score == pytest.approx(0.42)


def test_scan_match_returns_empty_for_quiet_match():
    """A match with no aggressive damage, no low life, no fast spells
    should produce zero candidates."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(1, ["You play Island"]),
        _turn(2, ["Opp plays Forest"]),
    ]}])
    out = scanner.scan_match("m-quiet", transcript)
    assert out == []


def test_scan_match_returns_list_of_candidates():
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(5, ["You life: 4", "You play Mountain"]),
    ]}])
    out = scanner.scan_match("m-stab", transcript)
    # At minimum, the result is a list (may be empty if heuristics don't fire)
    assert isinstance(out, list)
    for c in out:
        assert hasattr(c, "category") and hasattr(c, "heuristic_score")


def test_find_lethal_fires_when_opp_dies_after_3_plus_spells():
    """Spec heuristic: cast >= 3 noncreature spells AND opp life
    went from >= 8 to 0 in one turn."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(6, ["Opp life: 12"]),
        _turn(7, [
            "Opp life: 12",
            "You cast Burst Lightning → opponent",
            "You cast Burst Lightning → opponent",
            "You cast Burst Lightning → opponent",
            "You cast Burst Lightning → opponent",
            "Opp life: 0",
        ]),
    ]}])
    out = scanner.scan_match("m-lethal", transcript)
    lethal = [c for c in out if c.category == "find_lethal"]
    assert len(lethal) >= 1
    c = lethal[0]
    assert c.turn_num == 7
    assert 0.0 < c.heuristic_score <= 1.0


def test_find_lethal_does_not_fire_for_low_spell_count():
    """One spell is not a find-lethal puzzle, even if opp died."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(7, [
            "Opp life: 12",
            "You cast Lightning Bolt → opponent",
            "Opp life: 0",
        ]),
    ]}])
    out = scanner.scan_match("m-one", transcript)
    lethal = [c for c in out if c.category == "find_lethal"]
    assert lethal == []


def test_stabilize_fires_when_low_life_and_match_continued():
    """Spec heuristic: turn N where your life <= 5 AND match continued
    past N AND you eventually won."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(6, ["You life: 4"]),
        _turn(7, ["You life: 6"]),  # survived the spot
        _turn(8, ["Opp life: 0"]),  # eventually won
    ]}])
    out = scanner.scan_match("m-stab", transcript)
    stab = [c for c in out if c.category == "stabilize"]
    assert len(stab) >= 1
    assert stab[0].turn_num == 6  # the low-life turn


def test_stabilize_does_not_fire_if_match_ended_with_loss():
    """If you died, the low-life turn isn't a stabilize candidate."""
    from analysis.puzzles import scanner
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(6, ["You life: 4"]),
        _turn(7, ["You life: 0"]),  # died
    ]}])
    out = scanner.scan_match("m-lose", transcript)
    stab = [c for c in out if c.category == "stabilize"]
    assert stab == []


def test_tempo_fires_when_multiple_instants_cast_on_own_turn(monkeypatch):
    """Simplified Phase 2 heuristic: 2+ instants cast on your own turn.

    Patches card_data lookup so the test doesn't depend on prod DB."""
    from analysis.puzzles import scanner

    def _fake_is_instant(name: str) -> bool:
        return name.strip() in {"Burst Lightning", "Boomerang Basics"}

    monkeypatch.setattr(scanner, "_is_instant_card", _fake_is_instant)
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(5, [
            "You cast Burst Lightning → opp creature",
            "You cast Boomerang Basics → opp permanent",
        ], active_seat=1),
    ]}])
    out = scanner.scan_match("m-tempo", transcript)
    tempo = [c for c in out if c.category == "tempo"]
    assert len(tempo) >= 1
    assert tempo[0].turn_num == 5


def test_tempo_does_not_fire_on_opp_turn(monkeypatch):
    """Instants cast on opp's turn are reactive, not tempo mis-plays."""
    from analysis.puzzles import scanner
    monkeypatch.setattr(scanner, "_is_instant_card",
                         lambda n: n.strip() in {"Burst Lightning"})
    transcript = _fake_transcript([{"game_num": 1, "turns": [
        _turn(5, [
            "You cast Burst Lightning → opp creature",
            "You cast Burst Lightning → opp creature",
        ], active_seat=2),  # opp's turn
    ]}])
    out = scanner.scan_match("m-tempo-opp", transcript)
    tempo = [c for c in out if c.category == "tempo"]
    assert tempo == []


def test_scan_all_walks_cache_dir(tmp_path, monkeypatch):
    """scan_all() walks every *.json in CACHE_DIR and aggregates Candidates."""
    from analysis.puzzles import scanner
    monkeypatch.setattr(scanner, "CACHE_DIR", tmp_path)
    # Drop one stabilize-shaped match + one quiet match
    (tmp_path / "stab.json").write_text(json.dumps(_fake_transcript([
        {"game_num": 1, "turns": [
            _turn(6, ["You life: 4"]),
            _turn(7, ["You life: 6"]),
            _turn(8, ["Opp life: 0"]),
        ]},
    ])))
    (tmp_path / "quiet.json").write_text(json.dumps(_fake_transcript([
        {"game_num": 1, "turns": [_turn(1, ["You play Island"])]},
    ])))
    out = scanner.scan_all()
    # At least the stabilize one
    cats = [c.category for c in out]
    assert "stabilize" in cats


def test_scan_all_returns_empty_for_missing_cache_dir(tmp_path, monkeypatch):
    from analysis.puzzles import scanner
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(scanner, "CACHE_DIR", missing)
    assert scanner.scan_all() == []


def test_find_lethal_with_real_transcript_format():
    """Real format: 'ViewtifulYosh life: 8 → 0 (-8)' with opp_name passed."""
    from analysis.puzzles import scanner
    transcript = {
        "match_id": "real-fmt",
        "opp_name": "ViewtifulYosh",
        "games": [{"game_num": 1, "turns": [
            _turn(7, [
                "You cast Burst Lightning",
                "You cast Boomerang Basics",
                "You cast Slickshot Show-Off",
                "ViewtifulYosh life: 8 → 0 (-8)",
            ]),
        ]}],
    }
    out = scanner.scan_match("real-fmt", transcript)
    lethal = [c for c in out if c.category == "find_lethal"]
    assert len(lethal) >= 1
    assert lethal[0].turn_num == 7


def test_stabilize_with_real_transcript_format():
    """Real format: 'You life: 7 → 4 (-3)' with opp_name passed."""
    from analysis.puzzles import scanner
    transcript = {
        "match_id": "real-stab",
        "opp_name": "ViewtifulYosh",
        "games": [{"game_num": 1, "turns": [
            _turn(6, ["You life: 7 → 4 (-3)"]),
            _turn(7, ["You life: 4 → 6 (+2)"]),
            _turn(8, ["ViewtifulYosh life: 5 → 0 (-5)"]),
        ]}],
    }
    out = scanner.scan_match("real-stab", transcript)
    stab = [c for c in out if c.category == "stabilize"]
    assert len(stab) >= 1
    assert stab[0].turn_num == 6
