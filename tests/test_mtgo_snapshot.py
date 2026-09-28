import json
import os
import time
from datetime import date

from scrapers import mtgo_snapshot as s


def _mtgo(tmp_path, session="25695aea-064e-4792-8f4f-64d2d7b904b3", log_body="x" * 50):
    base = tmp_path / "Apps"
    app = base / "Data" / "A" / "B" / "mtgo..tion_1_0003.0004_a8b2b40868bb7cf6" / "Data" / "AppFiles" / "HASH"
    app.mkdir(parents=True)
    (app / "Match_GameLog_g1.dat").write_bytes(b"dat-one")
    (app / "Match_GameChat_g1.dat").write_bytes(b"private chat")
    (app / "PrivateChatChannel_Private_Bob.dat").write_bytes(b"private dm")
    (app / "mtgo_game_history").write_bytes(b"history-v1")
    (app / "grouping abc.xml").write_text("<deck/>")
    logs = base / "X" / "Y" / "mtgo..tion_1_0003.0004_a8b2b40868bb7cf6" / "Logs"
    logs.mkdir(parents=True)
    (logs / "mtgo.log").write_text(
        f"08:54:01 [INF] (SESSION|Start Session) Starting MtGO logging session.\n"
        f"08:54:01 [INF] (Initialization|SessionStarted) ID: {session}\n{log_body}\n")
    return base, app, logs


def test_snapshot_copies_logs_history_decks_but_never_chat(tmp_path):
    base, app, logs = _mtgo(tmp_path)
    dest = tmp_path / "raw"
    res = s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 28))
    day = dest / "2026-09-28"
    names = sorted(p.name for p in day.iterdir())
    assert "Match_GameLog_g1.dat" in names
    assert "mtgo_a8b2b408_25695aea.log" in names
    assert "a8b2b408__mtgo_game_history" in names
    assert "a8b2b408__grouping abc.xml" in names
    assert not [n for n in names if "Chat" in n]
    man = json.loads((day / "MANIFEST.json").read_text())
    assert {m["file"] for m in man} >= {"Match_GameLog_g1.dat", "mtgo_a8b2b408_25695aea.log"}
    assert all(len(m["sha256"]) == 64 for m in man)
    assert res["copied"] == 4


def test_second_run_copies_nothing_unchanged(tmp_path):
    base, app, logs = _mtgo(tmp_path)
    dest = tmp_path / "raw"
    s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 28))
    res = s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 29))
    assert res["copied"] == 0
    assert not (dest / "2026-09-29").exists()


def test_growing_session_log_is_refreshed_in_place(tmp_path):
    base, app, logs = _mtgo(tmp_path)
    dest = tmp_path / "raw"
    s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 28))
    with open(logs / "mtgo.log", "a") as fh:
        fh.write("more lines\n" * 10)
    res = s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 28))
    assert res["copied"] == 1
    kept = dest / "2026-09-28" / "mtgo_a8b2b408_25695aea.log"
    assert kept.read_text().count("more lines") == 10


def test_new_session_is_saved_separately(tmp_path):
    base, app, logs = _mtgo(tmp_path)
    dest = tmp_path / "raw"
    s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 28))
    (logs / "mtgo.log").write_text(
        "09:00:00 [INF] (Initialization|SessionStarted) ID: ffffffff-0000-0000-0000-000000000000\n")
    s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 29))
    logs_saved = sorted(p.name for p in dest.rglob("mtgo_*.log"))
    assert logs_saved == ["mtgo_a8b2b408_25695aea.log", "mtgo_a8b2b408_ffffffff.log"]


def test_changed_history_gets_a_new_copy(tmp_path):
    base, app, logs = _mtgo(tmp_path)
    dest = tmp_path / "raw"
    s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 28))
    (app / "mtgo_game_history").write_bytes(b"history-v2-longer")
    res = s.snapshot(root=base, dest_root=dest, today=date(2026, 9, 29))
    assert res["copied"] == 1
    assert (dest / "2026-09-29" / "a8b2b408__mtgo_game_history").read_bytes() == b"history-v2-longer"


def test_no_mtgo_install_is_a_quiet_noop(tmp_path):
    res = s.snapshot(root=tmp_path / "nothing", dest_root=tmp_path / "raw", today=date(2026, 9, 28))
    assert res == {"copied": 0, "dest": None}


def test_watcher_tick_reports_and_survives_errors(monkeypatch):
    from gui.mtgo_snapshot_watcher import MtgoSnapshotWatcher
    msgs = []
    w = MtgoSnapshotWatcher()
    w.status_changed.connect(msgs.append)
    monkeypatch.setattr(s, "snapshot", lambda: {"copied": 2, "dest": "x"})
    assert w.tick() == 2 and msgs[-1] == "MTGO snapshot: saved 2 file(s)"

    def boom():
        raise PermissionError("locked")
    monkeypatch.setattr(s, "snapshot", boom)
    assert w.tick() == 0 and "locked" in msgs[-1]


def test_raw_root_lives_beside_the_db_not_the_checkout(monkeypatch, tmp_path):
    from pathlib import Path
    from db import database
    monkeypatch.delenv("MTGO_RAW_DIR", raising=False)
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "mtg_meta.db"))
    assert s.raw_root() == tmp_path / "raw" / "mtgo"
    monkeypatch.setenv("MTGO_RAW_DIR", str(tmp_path / "elsewhere"))
    assert s.raw_root() == Path(tmp_path / "elsewhere")
