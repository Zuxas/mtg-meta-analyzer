"""#16: the scheduled fill must report failure instead of silent success.

Two mechanisms hid failures:
  (1) `background_fill.bat` self-relaunched (`start /min ... & exit`), so the
      Task-Scheduler process returned exit 0 INSTANTLY, before any work ran.
  (2) `run_fill_from_prefs.main()` returned no exit code, and the .bat ignored
      the Python exit code anyway.

Now `main()` exits non-zero when a CORE step fails (per-format scrape steps +
archive maintenance; enrichment/throttled steps stay best-effort), decided by
the pure `pipeline_failures()` helper, and the .bat propagates the code.
"""
from pathlib import Path

from scripts.run_fill_from_prefs import pipeline_failures

BAT = Path(__file__).resolve().parent.parent / "background_fill.bat"


# ---- pipeline_failures (the exit-code decision) ---------------------------

def test_all_ok_yields_no_failures():
    outcomes = {"modern": [("MTGTop8 -- modern", 0)],
                "standard": [("MTGMelee -- standard", 0)]}
    assert pipeline_failures(outcomes, maint_rc=0) == []


def test_a_failed_scrape_step_is_surfaced():
    outcomes = {"modern": [("MTGTop8 -- modern", 1)],
                "standard": [("MTGMelee -- standard", 0)]}
    assert pipeline_failures(outcomes, maint_rc=0) == ["modern/MTGTop8 -- modern"]


def test_archive_maintenance_failure_is_surfaced():
    assert pipeline_failures({}, maint_rc=1) == ["Archive maintenance"]


def test_multiple_failures_all_reported():
    outcomes = {"modern": [("a", 2), ("b", 0)], "pioneer": [("c", 1)]}
    assert set(pipeline_failures(outcomes, maint_rc=1)) == {
        "modern/a", "pioneer/c", "Archive maintenance",
    }


# ---- background_fill.bat --------------------------------------------------

def _bat_code() -> str:
    """The .bat with REM comment lines stripped (a comment may legitimately
    quote the removed `start /min` command)."""
    lines = BAT.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(ln for ln in lines
                     if not ln.strip().upper().startswith("REM")
                     and not ln.strip().startswith("::"))


def test_bat_does_not_self_relaunch():
    assert "start /min" not in _bat_code(), (
        "background_fill.bat must not self-relaunch -- that returns exit 0 to "
        "Task Scheduler before any work runs (#16)"
    )


def test_bat_propagates_the_pipeline_exit_code():
    code = _bat_code()
    assert "SET FILL_RC=%ERRORLEVEL%" in code, "must capture the pipeline exit code (#16)"
    assert "exit /b %FILL_RC%" in code, "must propagate the pipeline exit code (#16)"
