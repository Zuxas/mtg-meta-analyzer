"""Tests for per-replay notes/marks persistence in db/match_log.py."""
import pytest


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    yield


def test_get_defaults_when_absent(tmp_db):
    from db.match_log import get_replay_notes
    data = get_replay_notes("no-such-match")
    assert data == {"text": "", "marks": []}


def test_save_creates_stub_then_get_roundtrips(tmp_db):
    from db.match_log import save_replay_notes, get_replay_notes
    assert save_replay_notes("arena-1", "passed priority T7", [3, 1, 3]) is True
    data = get_replay_notes("arena-1")
    assert data["text"] == "passed priority T7"
    assert data["marks"] == [1, 3]            # deduped + sorted


def test_save_updates_existing_row(tmp_db):
    from db.match_log import save_match, save_replay_notes, get_replay_notes
    mid = save_match("FNM", "2026-05-25", "standard", 1, "Izzet Prowess",
                     "Golgari", match_id=None)
    from db.database import get_connection
    with get_connection() as c:
        c.execute("UPDATE match_log SET arena_match_id=? WHERE id=?",
                  ("arena-2", mid))
    assert save_replay_notes("arena-2", "note", [5]) is True
    with get_connection() as c:
        n = c.execute("SELECT COUNT(*) FROM match_log WHERE arena_match_id=?",
                      ("arena-2",)).fetchone()[0]
    assert n == 1
    assert get_replay_notes("arena-2") == {"text": "note", "marks": [5]}


def test_empty_arena_id_is_noop(tmp_db):
    from db.match_log import save_replay_notes, get_replay_notes
    assert save_replay_notes("", "x", [1]) is False
    assert get_replay_notes("") == {"text": "", "marks": []}


def test_stub_row_excluded_from_get_matches(tmp_db):
    # A notes-only stub must NOT appear as a phantom blank match in listings.
    from db.match_log import save_match, save_replay_notes, get_matches
    real = save_match("FNM", "2026-05-25", "standard", 1, "Izzet", "Golgari")
    save_replay_notes("arena-stub", "notes only", [1])   # creates a stub row
    rows = get_matches()
    assert "replay_notes_stub" not in {r.get("source") for r in rows}
    assert any(r["id"] == real for r in rows)            # real match still shown
