"""scripts/run_fill_from_prefs.py: with stdout redirected to a file (background_fill.bat appends
to logs/background_fill.log), every step heading must appear BEFORE that step's child output.
Reproduced 2026-10-01: the parent's print() was block-buffered when redirected while the child
wrote straight to the shared file handle, so all child output landed above all headings."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DRIVER = r"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rf", sys.argv[1])
rf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rf)
for fmt in ("modern", "standard", "legacy"):
    rf.run("-c print('CHILD-OUTPUT-" + fmt + "')", "MTGMelee - " + fmt)
"""


def test_redirected_headings_precede_child_output(tmp_path):
    out = tmp_path / "background_fill.log"
    with open(out, "w", encoding="utf-8") as f:
        subprocess.run([sys.executable, "-c", DRIVER, os.path.join(ROOT, "scripts", "run_fill_from_prefs.py")],
                       stdout=f, stderr=subprocess.STDOUT, cwd=ROOT, check=True,
                       env={k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"})
    lines = [l.strip() for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    order = [l for l in lines if l.startswith("-- MTGMelee") or l.startswith("CHILD-OUTPUT")]
    want = []
    for fmt in ("modern", "standard", "legacy"):
        label = "MTGMelee - " + fmt
        want += [f"-- {label} " + "-" * max(0, 55 - len(label)), "CHILD-OUTPUT-" + fmt]
    assert order == want, order
