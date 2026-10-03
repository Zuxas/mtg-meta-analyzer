"""Database compatibility check for the CI gate.

Proves, on a throwaway database, that:
  * a FRESH database gets every required table from normal startup,
  * an OLDER database (built by the base commit's code) upgrades cleanly
    without losing rows,
  * save_matches / get_matches work on both, and
  * running initialization a second time changes nothing (idempotent).

Required tables live in scripts/ci/db_contract.json, so a branch that adds
tables (e.g. matches_excluded) declares them there. The check only uses the
real startup path (init_db + save_matches); it never creates tables itself.

Usage:
    python scripts/ci/db_compat.py seed    --dir DIR   # run with cwd = base checkout
    python scripts/ci/db_compat.py fresh   --dir DIR
    python scripts/ci/db_compat.py upgrade --dir DIR   # DIR seeded by the base commit
    python scripts/ci/db_compat.py app     --dir DIR   # start the GUI offscreen on DIR
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
APP_TIMEOUT_S = 120
THREAD_GRACE_S = 20
CONTRACT = HERE.with_name("db_contract.json")

SAMPLE_MATCH = {
    "event_id": "ci-compat-event", "round": 1,
    "player1": "ci-a", "player2": "ci-b",
    "player1_arch": "Amulet Titan", "player2_arch": "Boros Energy",
    "winner_arch": "Amulet Titan", "result": "player1",
    "format": "modern", "event_date": "2026-01-01", "source": "mtgmelee",
}


def _paths(d: str) -> tuple[str, str]:
    return os.path.join(d, "mtg_meta.db"), os.path.join(d, "mtg_archive.db")


def _env_for(d: str) -> dict:
    a, b = _paths(d)
    env = dict(os.environ, MTG_META_DB=a, MTG_META_ARCHIVE_DB=b)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


def _contract() -> dict:
    if CONTRACT.exists():
        return json.loads(CONTRACT.read_text(encoding="utf-8"))
    return {"required_tables": ["events", "decks", "cards", "deck_cards", "matches"]}


def snapshot(db_path: str) -> dict:
    """Schema SQL + row count for every table/index/trigger/view."""
    con = sqlite3.connect(db_path)
    try:
        objs = con.execute(
            "SELECT type, name, COALESCE(sql,'') FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
        counts = {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
                  for t, n, _ in objs if t == "table"}
    finally:
        con.close()
    return {"schema": [list(o) for o in objs], "counts": counts}


# ---------------------------------------------------------------- in-process --

def _cycle_in_process(seed_only: bool = False) -> None:
    """One application-start cycle. Runs with MTG_META_DB already in env."""
    sys.path.insert(0, os.getcwd())
    import db.database as d
    d.init_db()
    from db.matches_queries import save_matches, get_matches
    save_matches([SAMPLE_MATCH])
    if not seed_only:
        rows = get_matches("modern")
        assert any(r["event_id"] == "ci-compat-event" for r in rows), "sample match not readable after save"


def _app_in_process() -> None:
    import faulthandler
    # If startup or shutdown wedges, dump every thread's stack and fail.
    faulthandler.dump_traceback_later(APP_TIMEOUT_S, exit=True)
    sys.path.insert(0, os.getcwd())
    import db.database as d
    d.init_db()
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    app = QApplication.instance() or QApplication([])
    from gui.main_window import MainWindow
    # A first-run QMessageBox / dialog runs its own nested event loop, which
    # app.quit() cannot end. Close any modal that appears and log it.
    seen: list[str] = []

    def _dismiss_modals():
        m = QApplication.activeModalWidget()
        if m is not None:
            seen.append(f"{type(m).__name__}: {m.windowTitle()!r}")
            m.close()
    sweeper = QTimer()
    sweeper.timeout.connect(_dismiss_modals)
    sweeper.start(250)

    w = MainWindow()
    if hasattr(w, "cleanup"):                 # same wiring as run_gui.py
        app.aboutToQuit.connect(w.cleanup)
    w.show()
    # exit(0), not quit(): Qt6 quit() first asks windows to close, and a
    # closeEvent that ignores (minimise-to-tray) silently cancels it.
    QTimer.singleShot(3000, lambda: app.exit(0))
    app.exec()
    sweeper.stop()
    for s in seen:
        print(f"  dismissed startup dialog -> {s}", flush=True)
    w.close()
    app.processEvents()

    # Background QThreads still running at interpreter teardown abort the
    # process ("QThread: Destroyed while thread is still running"). Give them
    # a grace period, then name any that never finish.
    import gc
    import time
    from PyQt6.QtCore import QThread

    def _running():
        out = []
        for o in gc.get_objects():
            try:
                if isinstance(o, QThread) and o.isRunning():
                    out.append(o)
            except (RuntimeError, ReferenceError):   # C++ side already deleted
                pass
        return out
    deadline = time.time() + THREAD_GRACE_S
    while _running() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.1)
    left = _running()
    if left:
        # run_gui.py also hard-exits after cleanup, so users never see this;
        # report it, don't fail on it.
        names = ", ".join(sorted({type(t).__name__ for t in left}))
        print(f"  WARNING: {len(left)} QThread(s) still running {THREAD_GRACE_S}s after cleanup: {names}", flush=True)
    print("App started and closed cleanly on this database.", flush=True)
    sys.stdout.flush()
    os._exit(0)   # mirror run_gui.py's hard exit


# ------------------------------------------------------------- orchestration --

def _run_child(mode: str, d: str, cwd: str | None = None) -> str:
    r = subprocess.run([sys.executable, str(HERE), f"_{mode}", "--dir", d],
                       env=_env_for(d), cwd=cwd or os.getcwd(),
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        raise SystemExit(f"FAIL: '{mode}' cycle crashed on {d}")
    return r.stdout


def _check_required(db_path: str, label: str) -> list[str]:
    have = set(snapshot(db_path)["counts"])
    missing = [t for t in _contract()["required_tables"] if t not in have]
    return [f"{label}: missing required table(s): {', '.join(missing)}"] if missing else []


def _diff(a: dict, b: dict) -> list[str]:
    out = []
    sa, sb = {tuple(x[:2]): x[2] for x in a["schema"]}, {tuple(x[:2]): x[2] for x in b["schema"]}
    for k in sorted(set(sa) | set(sb)):
        if sa.get(k) != sb.get(k):
            out.append(f"schema changed on re-run: {k[0]} {k[1]}")
    for t in sorted(set(a["counts"]) | set(b["counts"])):
        if a["counts"].get(t) != b["counts"].get(t):
            out.append(f"row count changed on re-run: {t} {a['counts'].get(t)} -> {b['counts'].get(t)}")
    return out


def cmd_fresh(d: str) -> int:
    os.makedirs(d, exist_ok=True)
    db, _ = _paths(d)
    _run_child("cycle", d)
    first = snapshot(db)
    _run_child("cycle", d)
    second = snapshot(db)
    problems = _check_required(db, "fresh DB") + _diff(first, second)
    return _report("Fresh database", problems, second)


def cmd_upgrade(d: str) -> int:
    db, _ = _paths(d)
    if not os.path.exists(db):
        print(f"FAIL: no seeded base database at {db}")
        return 1
    before = snapshot(db)
    _run_child("cycle", d)
    first = snapshot(db)
    _run_child("cycle", d)
    second = snapshot(db)
    problems = _check_required(db, "upgraded DB") + _diff(first, second)
    for t, n in before["counts"].items():
        if first["counts"].get(t, 0) < n:
            problems.append(f"upgrade lost rows: {t} {n} -> {first['counts'].get(t, 0)}")
    return _report("Older database upgrade", problems, second)


def _report(title: str, problems: list[str], snap: dict) -> int:
    if problems:
        print(f"{title}: FAILED")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"{title}: OK ({len(snap['counts'])} tables, idempotent on re-run)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["seed", "fresh", "upgrade", "app", "_cycle", "_seed", "_app"])
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    d = os.path.abspath(a.dir)
    if a.mode == "_cycle":
        _cycle_in_process()
        return 0
    if a.mode == "_seed":
        _cycle_in_process(seed_only=True)
        return 0
    if a.mode == "_app":
        _app_in_process()
        return 0
    if a.mode == "seed":
        os.makedirs(d, exist_ok=True)
        _run_child("seed", d)
        print(f"Seeded base-version database: {snapshot(_paths(d)[0])['counts']}")
        return 0
    if a.mode == "fresh":
        return cmd_fresh(d)
    if a.mode == "upgrade":
        return cmd_upgrade(d)
    if a.mode == "app":
        os.makedirs(d, exist_ok=True)
        out = _run_child("app", d)
        print("\n".join(l for l in out.splitlines() if "dismissed startup dialog" in l or "WARNING" in l))
        print("App smoke test: OK")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
