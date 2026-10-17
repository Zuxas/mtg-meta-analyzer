"""#31: the Backfill worker must survive being run twice in one process.

run() replaced sys.stdout with a new TextIOWrapper each time. On the second
run the first wrapper was garbage-collected and closed the shared buffer, so
every scraper's first print raised "I/O operation on closed file" and each
step was reported as an error; nothing was scraped.
"""
import gc
import io
import sys


def test_backfill_worker_runs_twice(monkeypatch):
    # Plain QApplication, like the other Qt tests: pytest-qt (qapp) is not a dependency.
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841 -- keep a reference
    import scrapers.mtgtop8 as mtgtop8
    import analysis.archetypes as archetypes
    from gui.tabs.settings import _BackfillWorker

    # A console-like stdout: a text wrapper over a byte buffer.
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    monkeypatch.setattr(mtgtop8, "run", lambda **kw: print("scraping", kw["format_name"]))
    monkeypatch.setattr(archetypes, "apply_normalization", lambda **kw: None)

    for _ in range(2):
        worker = _BackfillWorker(["standard"], ["mtgtop8_latest"], pages=1)
        done = []
        worker.finished_ok.connect(done.append)
        worker.run()                 # synchronously, on this thread
        del worker
        gc.collect()                 # where the orphaned wrapper used to close the buffer
        assert done == ["Done! Scraped 1 format/source combinations."]

    print("still writable")          # stdout survived both runs
