"""#20: launchers must work from any clone, so no hardcoded drive paths."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bats():
    out = subprocess.run(["git", "ls-files", "*.bat"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split()
    return [ROOT / p for p in out]


def test_no_drive_letter_paths_or_locale_dates_in_bat_files():
    assert _bats(), "no .bat files found"
    bad = []
    for p in _bats():
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().upper().startswith("REM"):
                continue
            if re.search(r"\b[A-Za-z]:\\", line) or "%DATE:~" in line:
                bad.append(f"{p.name}:{n}: {line.strip()}")
    assert not bad, "\n".join(bad)
