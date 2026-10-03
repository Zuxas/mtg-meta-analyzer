"""
The scheduled scrape sources, in ONE place, plus a step runner that keeps the
error class of a failed step.

Used by scripts/run_fill_from_prefs.py (the 6 AM / 5 PM pipeline),
scripts/recover_source.py (targeted recovery) and analysis/source_recency.py
(which sources a format is EXPECTED to have fresh data from). Qt-free.

Why (2026-10-03): matches from MTGMelee stopped at 2026-09-13 for Standard and
Legacy, 2026-09-19 for Modern and 2026-05-09 for Pioneer while MTGTop8 events
stayed current, and the only evidence was a per-format "ok". The 2026-10-03
06:00 run was killed mid-pipeline (exit 0xC000013A) and recorded nothing.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Formats MTGMelee is scraped for regardless of the user's selection.
MELEE_ALWAYS = ("legacy", "pauper")

# Sources the scheduled pipeline runs. `kind` is the table the source fills, so
# recency is read from the right place: events.source / matches.source.
SOURCES = {
    "mtgtop8": {"label": "MTGTop8", "kind": "events",
                "cmd": "main.py --format {fmt} --pages {pages} --max-events 50",
                "pages": 2},
    "mtgmelee": {"label": "MTGMelee", "kind": "matches",
                 "cmd": "-m scrapers.mtgmelee_scraper --format {fmt} --pages {pages}",
                 "pages": 3},
}


def scheduled_sources(fmt: str, selected_formats) -> list[str]:
    """Sources the pipeline runs for `fmt` given the user's selected formats."""
    fmt = fmt.lower()
    selected = {f.lower() for f in selected_formats}
    out = []
    if fmt in selected:
        out.append("mtgtop8")
    if fmt in selected or fmt in MELEE_ALWAYS:
        out.append("mtgmelee")
    return out


def step_command(source: str, fmt: str, pages: int | None = None) -> str:
    spec = SOURCES[source]
    return spec["cmd"].format(fmt=fmt, pages=pages or spec["pages"])


def step_label(source: str, fmt: str) -> str:
    return f"{SOURCES[source]['label']} — {fmt}"


# --- running a step -----------------------------------------------------------

# Windows: the console was closed / Ctrl+C / Ctrl+Break. POSIX: negative signal.
_INTERRUPT_CODES = {0xC000013A, 3221225786, -2, 130}
_EXC_LINE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b")
_TB_LAST = re.compile(r"^([A-Za-z_][\w.]*)(?::|$)")    # unindented final traceback line


@dataclass
class StepResult:
    rc: int
    error_class: str | None = None
    stderr_tail: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.rc == 0


def classify_failure(rc: int, stderr_lines) -> str | None:
    """None for success; else 'interrupted', the last exception class seen on
    stderr (e.g. 'requests.exceptions.ConnectionError'), or 'exit <rc>'."""
    if rc == 0:
        return None
    if rc in _INTERRUPT_CODES or (rc < 0 and rc != -1):
        return "interrupted"
    lines = list(stderr_lines)
    # A Python traceback ends with an unindented 'pkg.ExcName: message' line --
    # take it whatever the class is called (requests' ConnectTimeout has no
    # Error suffix).
    tb = max((i for i, l in enumerate(lines) if l.startswith("Traceback (most recent call")),
             default=None)
    if tb is not None:
        for line in reversed(lines[tb + 1:]):
            m = _TB_LAST.match(line)
            if m:
                return m.group(1)
    for line in reversed(lines):                    # no traceback: logged 'XxxError: ...'
        m = _EXC_LINE.match(line.strip())
        if m:
            return m.group(1)
    return f"exit {rc}"


def run_step(cmd: str, label: str, *, cwd: str = _ROOT, tail: int = 40) -> StepResult:
    """Run one pipeline step as a child Python process.

    stdout is inherited (goes straight to the log, as before). stderr is copied
    line by line to our stderr as it arrives -- so the log still streams -- while
    the last `tail` lines are kept to name the failure's exception class.
    The heading is flushed before the child starts (see 2026-10-01 log-order fix).
    """
    print(f"\n-- {label} " + "-" * max(0, 55 - len(label)), flush=True)
    proc = subprocess.Popen(
        [sys.executable] + cmd.split(), cwd=cwd,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    last = deque(maxlen=tail)

    def _pump():
        for line in proc.stderr:
            last.append(line.rstrip("\n"))
            sys.stderr.write(line)
            sys.stderr.flush()
    t = threading.Thread(target=_pump, daemon=True)
    t.start()
    rc = proc.wait()
    t.join(timeout=5)
    res = StepResult(rc=rc, error_class=classify_failure(rc, last), stderr_tail=list(last))
    if not res.ok:
        print(f"  [warn] exited with code {rc} ({res.error_class})", flush=True)
    return res
