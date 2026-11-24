"""#17: the scheduled pipeline must never mass-rename the live DB unattended.

`scripts/run_fill_from_prefs.py` is the 6 AM background job. It used to run
`python -m analysis.archetypes --apply`, a format-blind `UPDATE decks SET
archetype` on the active DB with no backup and no audit. A new (possibly wrong)
alias would be mass-applied the next morning with no rollback. #17 removes the
unattended write: the nightly job now runs archetype normalization in DRY-RUN
mode (it logs the pending renames); applying them is a manual, backed-up step.

This is a source-scan guard (the real driver does network + DB work, so it
isn't unit-runnable) that pins the contract so the write can't creep back in.
"""
import re
from pathlib import Path

DRIVER = Path(__file__).resolve().parent.parent / "scripts" / "run_fill_from_prefs.py"


def _code() -> str:
    """Driver source with comment lines stripped (a comment may legitimately
    document the manual `--apply` command; only executed code matters here)."""
    src = DRIVER.read_text(encoding="utf-8")
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def test_scheduled_pipeline_never_applies_archetypes_unattended():
    code = _code()
    # No `analysis.archetypes --apply` executed by the scheduled driver, however spaced.
    assert not re.search(r"analysis\.archetypes\s+--apply", code), (
        "the 6 AM pipeline must NOT run `analysis.archetypes --apply` -- that is an "
        "unattended, un-backed-up mass rename of the live decks table (#17)"
    )
    # Defensive: no `--apply` passed to any run() step either.
    assert "--apply" not in code, (
        "the scheduled pipeline must not pass --apply to any step (#17)"
    )


def test_scheduled_pipeline_still_runs_normalization_as_dry_run():
    src = _code()
    # Normalization must still run (just without writing), so the pending renames
    # stay visible in the nightly log rather than being silently dropped.
    assert re.search(r'run\(\s*"-m analysis\.archetypes"', src), (
        "the dry-run archetype normalization step must remain in the pipeline (#17)"
    )
