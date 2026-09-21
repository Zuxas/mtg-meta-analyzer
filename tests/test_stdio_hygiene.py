"""No module may replace sys.stdout/stderr with a new TextIOWrapper at import.

`sys.stdout = io.TextIOWrapper(sys.stdout.buffer, ...)` orphans the previous
wrapper; when it is garbage-collected its __del__ closes the SHARED buffer, so
any caller that already wrapped stdout (a runner script, pytest's capture)
dies with "ValueError: I/O operation on closed file". It killed the MTGTop8
backfill runner on 2026-09-20 and, via scrapers/mtgmelee_scraper.py, an
import-smoke test on 2026-09-21. Use db.helpers.force_utf8_stdio(), which
reconfigures the existing streams in place.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN = [ROOT / "main.py", ROOT / "fill_database.py", ROOT / "run_gui.py",
        *sorted((ROOT / "scrapers").glob("*.py")),
        *sorted((ROOT / "scripts").glob("*.py")),
        *sorted((ROOT / "analysis").glob("*.py")),
        *sorted((ROOT / "db").glob("*.py"))]


def _module_level_rewraps(path: pathlib.Path) -> list[int]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits: list[int] = []

    def walk(nodes, guarded):
        for n in nodes:
            if isinstance(n, ast.If):
                t = n.test
                is_main = (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
                           and t.left.id == "__name__")
                walk(n.body, guarded or is_main)
                walk(n.orelse, guarded)
            elif isinstance(n, ast.Try):
                walk(n.body, guarded)
                for h in n.handlers:
                    walk(h.body, guarded)
                walk(n.finalbody, guarded)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            elif isinstance(n, ast.Assign) and not guarded:
                seg = ast.get_source_segment(src, n) or ""
                if "TextIOWrapper(sys.std" in seg:
                    hits.append(n.lineno)

    walk(tree.body, False)
    return hits


@pytest.mark.parametrize("path", [p for p in SCAN if p.exists() and not p.name.startswith("_")],
                         ids=lambda p: str(p.relative_to(ROOT)))
def test_no_module_level_stdout_rewrap(path):
    assert _module_level_rewraps(path) == [], \
        "replace with db.helpers.force_utf8_stdio() (in-place reconfigure)"


def test_force_utf8_stdio_reconfigures_in_place(monkeypatch):
    import gc, io, sys
    from db.helpers import force_utf8_stdio
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", wrapper)
    force_utf8_stdio()
    del wrapper
    gc.collect()
    sys.stdout.write("\u00c6ther\n")
    sys.stdout.flush()
    assert not buf.closed
    assert sys.stdout.encoding.lower().replace("-", "") == "utf8"
