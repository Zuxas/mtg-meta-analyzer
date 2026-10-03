"""scrape_state.json is written by two PROCESSES: the GUI (gui/tray_icon.py ->
write_scrape_state) and the scheduled scraper (run_fill_from_prefs ->
write_source_outcome / mark_run / write_scrape_state). Each write is
read -> modify -> replace, so without a cross-process lock one writer replaces
the file with a snapshot that predates the other's update and that update is
lost (PR #10 review). Two real processes write disjoint keys concurrently;
every key must survive."""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SCHEDULER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from db.scrape_state import write_source_outcome, mark_run
path, n, start = sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
while time.time() < start:
    pass
for i in range(n):
    write_source_outcome("modern", f"src{i}", "error" if i % 2 else "ok",
                         error_class="interrupted", path=path)
    mark_run("step", step=f"step{i}", path=path)
"""

_GUI = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from db.scrape_state import write_scrape_state
path, n, start = sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
while time.time() < start:
    pass
for i in range(n):
    write_scrape_state(status="ok", fmt=f"gui{i}", path=path)   # per-format, GUI-style
    write_scrape_state(status="ok", path=path)                  # global, as tray_icon does
"""


def _race(path, n=150):
    start = time.time() + 1.5
    procs = [subprocess.Popen([sys.executable, "-c", code, str(ROOT), str(path), str(n),
                               repr(start)], stderr=subprocess.PIPE, text=True)
             for code in (_SCHEDULER, _GUI)]
    for p in procs:
        _, err = p.communicate(timeout=180)
        assert p.returncode == 0, err
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_concurrent_gui_and_scheduler_writes_lose_nothing(tmp_path):
    n = 150
    state = _race(tmp_path / "scrape_state.json", n)
    sources = state["formats"]["modern"]["sources"]
    missing_src = [i for i in range(n) if f"src{i}" not in sources]
    missing_gui = [i for i in range(n) if f"gui{i}" not in state["formats"]]
    assert not missing_src, f"scheduler updates lost: {len(missing_src)}/{n}"
    assert not missing_gui, f"GUI updates lost: {len(missing_gui)}/{n}"
    assert state["last_status"] == "ok"                       # GUI global write survived
    assert state["runs"]["pipeline"]["last_step"] == f"step{n - 1}"
    assert sources[f"src{n - 1}"]["error_class"] == "interrupted"


def test_no_temp_files_left_behind(tmp_path):
    _race(tmp_path / "scrape_state.json", 40)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
