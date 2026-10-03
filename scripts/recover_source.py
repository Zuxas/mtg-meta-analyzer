"""
Targeted recovery for one stale (format, source), then verify (issue #8).

    python scripts/recover_source.py --format pioneer --source mtgmelee
    python scripts/recover_source.py --format modern --source mtgmelee --pages 10
    python scripts/recover_source.py --format modern --source mtgmelee --dry-run

Runs the SAME step the scheduled pipeline runs (db.scrape_sources), records its
outcome per source, re-measures recency from the rows, and prints before/after.

Exit status:
  0  the source is fresh after recovery
  1  the scrape step itself failed (error class printed)
  2  the scrape ran cleanly but the source is STILL not fresh -- the gap remains
     (upstream has nothing newer, or the scraper is skipping it). Loud on purpose.
  3  bad arguments (unknown source / source not scheduled for this format)
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

EXIT_OK, EXIT_SCRAPE_FAILED, EXIT_GAP_REMAINS, EXIT_USAGE = 0, 1, 2, 3


def _snap(rec: dict, source: str) -> dict:
    i = rec["sources"].get(source) or {}
    return {k: i.get(k) for k in ("last_date", "rows_30d", "days_stale", "status")}


def recover(fmt: str, source: str, *, pages=None, dry_run=False, runner=None,
            measure=None, record=None, out=print) -> int:
    """Testable core. `runner(cmd, label) -> StepResult`, `measure(fmt) -> recency
    dict for fmt`, `record(fmt, source, result)` are injectable."""
    from db.scrape_sources import SOURCES, run_step, step_command, step_label
    from db.scrape_state import write_source_outcome
    from analysis.source_recency import describe_recency, source_recency

    fmt = fmt.lower()
    if source not in SOURCES:
        out(f"unknown source {source!r}; known: {', '.join(SOURCES)}")
        return EXIT_USAGE
    measure = measure or (lambda f: source_recency([f])[f])
    runner = runner or (lambda cmd, label: run_step(cmd, label, cwd=_ROOT))
    record = record or (lambda f, s, r: write_source_outcome(
        f, s, "ok" if r.ok else "error", error=None if r.ok else f"recover: exit {r.rc}",
        error_class=r.error_class))

    before = measure(fmt)
    if not before["sources"].get(source, {}).get("scheduled"):
        out(f"{source} is not a scheduled source for {fmt}; nothing to recover")
        return EXIT_USAGE
    cmd, label = step_command(source, fmt, pages), f"RECOVER {step_label(source, fmt)}"
    out("BEFORE")
    for line in describe_recency(fmt, before):
        out("  " + line)
    if dry_run:
        out(f"DRY RUN -- would run: python {cmd}")
        return EXIT_OK

    res = runner(cmd, label)
    record(fmt, source, res)
    after = measure(fmt)
    b, a = _snap(before, source), _snap(after, source)
    out("AFTER")
    for line in describe_recency(fmt, after):
        out("  " + line)
    out(f"{source}/{fmt}: last_date {b['last_date']} -> {a['last_date']}, "
        f"rows_30d {b['rows_30d']} -> {a['rows_30d']}, status {b['status']} -> {a['status']}")

    if not res.ok:
        out(f"RECOVERY FAILED: scrape step failed ({res.error_class})")
        return EXIT_SCRAPE_FAILED
    if a["status"] != "fresh":
        gained = (a["rows_30d"] or 0) - (b["rows_30d"] or 0)
        out(f"RECOVERY INCOMPLETE: scrape ran cleanly (+{gained} rows in the last 30 days) "
            f"but {source}/{fmt} is still {a['status']}, data to {a['last_date']}. "
            "Upstream may have nothing newer, or the scraper is skipping events -- "
            "check its log before retrying with more --pages.")
        return EXIT_GAP_REMAINS
    out(f"RECOVERED: {source}/{fmt} is fresh (data to {a['last_date']})")
    return EXIT_OK


def main(argv=None) -> int:
    from db.scrape_sources import SOURCES
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--format", required=True)
    p.add_argument("--source", required=True, choices=sorted(SOURCES))
    p.add_argument("--pages", type=int, default=None,
                   help="pages to scan (default: the pipeline's own setting)")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    return recover(a.format, a.source, pages=a.pages, dry_run=a.dry_run)


if __name__ == "__main__":
    from db.helpers import force_utf8_stdio
    force_utf8_stdio()
    sys.exit(main())
