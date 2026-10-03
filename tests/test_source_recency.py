"""Per-source recency, diagnosis, scrape-outcome metadata and recovery (issue #8).

Fixtures mirror the live DB on 2026-10-03: MTGTop8 events current for every
format; MTGMelee matches stop at 2026-05-09 for Pioneer and mid-September for
Modern / Standard / Legacy; the 06:00 run was killed mid-pipeline (0xC000013A).
"""
import sqlite3
import sys
from datetime import date, timedelta

import pytest

from analysis.source_recency import describe_recency, source_recency
from db import scrape_sources as ss
from db.scrape_state import (format_scrape_state, mark_run, read_scrape_state, run_status,
                             write_source_outcome)

TODAY = date(2026, 10, 3)
SELECTED = ["modern", "standard", "pioneer", "legacy", "pauper"]


def _d(days_ago, mtgtop8_style=False):
    d = TODAY - timedelta(days=days_ago)
    return d.strftime("%d/%m/%y") if mtgtop8_style else d.isoformat()


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE events (source TEXT, format TEXT, date TEXT)")
    c.execute("CREATE TABLE matches (source TEXT, format TEXT, event_date TEXT)")
    return c


def _events(c, src, fmt, ages, top8_style=False):
    c.executemany("INSERT INTO events VALUES (?,?,?)",
                  [(src, fmt, _d(a, top8_style)) for a in ages])


def _matches(c, src, fmt, ages):
    c.executemany("INSERT INTO matches VALUES (?,?,?)", [(src, fmt, _d(a)) for a in ages])


def _rec(c, fmt, state=None, selected=SELECTED):
    return source_recency([fmt], selected, con=c, today=TODAY, state=state or {})[fmt]


# --- diagnosis ---------------------------------------------------------------

def test_pioneer_events_current_matches_months_behind(con):
    _events(con, "mtgtop8", "pioneer", [2, 3, 10], top8_style=True)   # dd/mm/yy, current
    _matches(con, "mtgmelee", "pioneer", [147, 150, 200])             # stops 2026-05-09
    r = _rec(con, "pioneer")
    assert r["diagnosis"] == "source_stale"
    assert r["events_without_matches"] is True
    assert r["fresh_sources"] == ["mtgtop8"] and r["stale_sources"] == ["mtgmelee"]
    assert r["sources"]["mtgmelee"]["last_date"] == "2026-05-09"
    assert r["sources"]["mtgmelee"]["status"] == "dead"
    assert r["format_status"] == "dead"            # agrees with data_health
    text = "\n".join(describe_recency("pioneer", r))
    assert "recover_source.py --format pioneer --source mtgmelee" in text


def test_whole_format_stale_is_not_source_stale(con):
    _events(con, "mtgtop8", "modern", [40, 45])
    _matches(con, "mtgmelee", "modern", [40, 50])
    r = _rec(con, "modern")
    assert r["diagnosis"] == "format_stale" and r["fresh_sources"] == []


def test_all_fresh_is_ok(con):
    _events(con, "mtgtop8", "pauper", [1, 2])
    _matches(con, "mtgmelee", "pauper", [2, 3])
    r = _rec(con, "pauper")
    assert r["diagnosis"] == "ok" and not r["events_without_matches"]


def test_no_rows_anywhere_is_no_data(con):
    assert _rec(con, "pioneer")["diagnosis"] == "no_data"


def test_unscheduled_sources_are_reported_but_never_drive_the_diagnosis(con):
    _events(con, "mtgtop8", "modern", [1])
    _matches(con, "mtgmelee", "modern", [2])
    _events(con, "mtgdecks", "modern", [150])      # auto-pull disabled since 2026-06
    r = _rec(con, "modern")
    assert r["diagnosis"] == "ok"
    assert r["sources"]["mtgdecks"]["scheduled"] is False
    assert any("mtgdecks: not scheduled" in l for l in describe_recency("modern", r))


def test_melee_always_format_not_selected_only_schedules_melee(con):
    _matches(con, "mtgmelee", "legacy", [1])
    _events(con, "mtgtop8", "legacy", [100])
    r = _rec(con, "legacy", selected=["modern"])
    assert r["sources"]["mtgtop8"]["scheduled"] is False
    assert r["diagnosis"] == "ok"


def test_scheduled_source_with_zero_rows_ever_is_listed_stale(con):
    _events(con, "mtgtop8", "pioneer", [1])
    r = _rec(con, "pioneer")
    assert r["stale_sources"] == ["mtgmelee"] and r["sources"]["mtgmelee"]["last_date"] is None


# --- scrape evidence in the explanation ---------------------------------------

def test_failed_scrape_names_error_class_and_last_success(con, tmp_path):
    p = tmp_path / "state.json"
    write_source_outcome("pioneer", "mtgmelee", "ok", path=p)
    write_source_outcome("pioneer", "mtgmelee", "error", error="exit 1",
                         error_class="requests.exceptions.ConnectTimeout", path=p)
    _events(con, "mtgtop8", "pioneer", [1])
    _matches(con, "mtgmelee", "pioneer", [150])
    line = [l for l in describe_recency("pioneer", _rec(con, "pioneer", read_scrape_state(p)))
            if "mtgmelee" in l and "FAILED" in l][0]
    assert "requests.exceptions.ConnectTimeout" in line and "last success 20" in line


def test_ok_scrape_but_stale_data_says_so(con, tmp_path):
    p = tmp_path / "state.json"
    write_source_outcome("pioneer", "mtgmelee", "ok", path=p)
    _events(con, "mtgtop8", "pioneer", [1])
    _matches(con, "mtgmelee", "pioneer", [150])
    text = "\n".join(describe_recency("pioneer", _rec(con, "pioneer", read_scrape_state(p))))
    assert "reported ok" in text and "no newer data" in text


# --- scrape_state: per-source outcomes and run markers ------------------------

def test_last_success_survives_failures_and_error_clears_on_success(tmp_path):
    p = tmp_path / "s.json"
    write_source_outcome("modern", "mtgmelee", "ok", path=p)
    ok_at = format_scrape_state("modern", path=p)["sources"]["mtgmelee"]["last_success"]
    write_source_outcome("modern", "mtgmelee", "error", error_class="interrupted", path=p)
    s = format_scrape_state("modern", path=p)["sources"]["mtgmelee"]
    assert s["last_status"] == "error" and s["last_success"] == ok_at
    assert s["error_class"] == "interrupted"
    write_source_outcome("modern", "mtgmelee", "ok", path=p)
    s = format_scrape_state("modern", path=p)["sources"]["mtgmelee"]
    assert "error_class" not in s and "last_error" not in s


def test_per_source_writes_keep_existing_format_and_global_keys(tmp_path):
    from db.scrape_state import write_scrape_state
    p = tmp_path / "s.json"
    write_scrape_state(status="ok", path=p)
    write_scrape_state(status="ok", fmt="modern", path=p)
    write_source_outcome("modern", "mtgtop8", "ok", path=p)
    st = read_scrape_state(p)
    assert st["last_status"] == "ok"
    assert st["formats"]["modern"]["last_status"] == "ok"
    assert st["formats"]["modern"]["sources"]["mtgtop8"]["last_status"] == "ok"


def test_run_markers_detect_an_interrupted_run(tmp_path):
    p = tmp_path / "s.json"
    assert run_status(path=p)["state"] == "never"
    mark_run("started", path=p)
    mark_run("step", step="MTGMelee — modern", path=p)
    rs = run_status(path=p)
    assert rs["state"] == "interrupted_or_running" and rs["last_step"] == "MTGMelee — modern"
    mark_run("finished", path=p)
    assert run_status(path=p)["state"] == "finished"


# --- error classes ------------------------------------------------------------

@pytest.mark.parametrize("rc,stderr,expected", [
    (0, [], None),
    (3221225786, [], "interrupted"),                 # 0xC000013A: console closed / Ctrl+C
    (-2, [], "interrupted"),                          # POSIX SIGINT
    (1, ["Traceback (most recent call last):", '  File "x.py", line 1',
         "requests.exceptions.ConnectTimeout: HTTPSConnectionPool(...)"],
     "requests.exceptions.ConnectTimeout"),
    (1, ["sqlite3.OperationalError: database is locked"], "sqlite3.OperationalError"),
    (2, ["usage: x", "error: bad arg"], "exit 2"),
])
def test_classify_failure(rc, stderr, expected):
    assert ss.classify_failure(rc, stderr) == expected


def test_run_step_streams_and_keeps_the_exception_class(tmp_path, capsys):
    script = tmp_path / "boom.py"
    script.write_text("import sys\nprint('working', flush=True)\nraise KeyError('nope')\n")
    res = ss.run_step(str(script), "boom step", cwd=str(tmp_path))
    assert res.rc != 0 and res.error_class == "KeyError"
    err = capsys.readouterr().err
    assert "KeyError" in err                         # stderr still reaches the log


def test_run_step_success(tmp_path):
    script = tmp_path / "fine.py"
    script.write_text("print('ok')\n")
    res = ss.run_step(str(script), "fine step", cwd=str(tmp_path))
    assert res.ok and res.error_class is None


def test_scheduled_sources_match_the_pipeline():
    assert ss.scheduled_sources("modern", SELECTED) == ["mtgtop8", "mtgmelee"]
    assert ss.scheduled_sources("pauper", ["modern"]) == ["mtgmelee"]   # MELEE_ALWAYS
    assert ss.scheduled_sources("vintage", SELECTED) == []
    assert ss.step_command("mtgmelee", "pioneer") == "-m scrapers.mtgmelee_scraper --format pioneer --pages 3"
    assert ss.step_command("mtgtop8", "modern", 5).startswith("main.py --format modern --pages 5")


# --- pipeline records each step immediately -----------------------------------

def test_pipeline_step_outcome_is_written_before_the_run_ends(tmp_path, monkeypatch):
    import scripts.run_fill_from_prefs as rf
    p = tmp_path / "s.json"
    monkeypatch.setattr(ss, "run_step",
                        lambda cmd, label, cwd=None: ss.StepResult(3221225786, "interrupted"))
    mark_run("started", path=p)
    outcomes = {}
    rf.run_source_step("mtgmelee", "modern", outcomes, state_path=p)
    # the run is "killed" here -- no record_format_outcomes, no mark_run('finished')
    s = format_scrape_state("modern", path=p)["sources"]["mtgmelee"]
    assert s["last_status"] == "error" and s["error_class"] == "interrupted"
    assert run_status(path=p)["state"] == "interrupted_or_running"
    assert outcomes == {"modern": [("MTGMelee — modern", 3221225786)]}


# --- recovery: verify after, loud when the gap remains --------------------------

def _rec_with(status, last):
    return {"diagnosis": "source_stale", "events_without_matches": True, "fresh_sources": [],
            "stale_sources": ["mtgmelee"] if status != "fresh" else [],
            "sources": {"mtgmelee": {"kind": "matches", "last_date": last, "rows_30d": 0,
                                     "rows_prev_30d": 0, "days_stale": 1, "status": status,
                                     "scheduled": True, "scrape": {"recorded": False}}}}


def _recover(before, after, result, **kw):
    from scripts.recover_source import recover
    seq, calls, out = [before, after], [], []
    rc = recover("pioneer", "mtgmelee", measure=lambda f: seq.pop(0),
                 runner=lambda cmd, label: calls.append(cmd) or result,
                 record=lambda f, s, r: None, out=out.append, **kw)
    return rc, calls, "\n".join(out)


def test_recover_ok_when_source_becomes_fresh():
    rc, calls, out = _recover(_rec_with("dead", "2026-05-09"), _rec_with("fresh", "2026-10-02"),
                              ss.StepResult(0))
    assert rc == 0 and "RECOVERED" in out
    assert calls == ["-m scrapers.mtgmelee_scraper --format pioneer --pages 3"]


def test_recover_nonzero_and_loud_when_gap_remains():
    rc, _, out = _recover(_rec_with("dead", "2026-05-09"), _rec_with("dead", "2026-05-09"),
                          ss.StepResult(0))
    assert rc == 2 and "RECOVERY INCOMPLETE" in out


def test_recover_reports_scrape_failure_class():
    rc, _, out = _recover(_rec_with("dead", "2026-05-09"), _rec_with("dead", "2026-05-09"),
                          ss.StepResult(1, "requests.exceptions.ConnectTimeout"))
    assert rc == 1 and "ConnectTimeout" in out


def test_recover_dry_run_runs_nothing_and_pages_override():
    from scripts.recover_source import recover
    calls, out = [], []
    rc = recover("pioneer", "mtgmelee", pages=10, dry_run=True,
                 measure=lambda f: _rec_with("dead", "2026-05-09"),
                 runner=lambda *a: calls.append(a), out=out.append)
    assert rc == 0 and calls == [] and "--pages 10" in "\n".join(out)


def test_recover_refuses_unscheduled_source():
    from scripts.recover_source import recover
    r = _rec_with("dead", None)
    r["sources"]["mtgmelee"]["scheduled"] = False
    assert recover("vintage", "mtgmelee", measure=lambda f: r, out=lambda *_: None) == 3
