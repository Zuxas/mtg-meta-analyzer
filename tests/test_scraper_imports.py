"""Every scraper module must import cleanly.

scrapers/backfill.py imported a name (HEADERS) that scrapers/mtgtop8.py stopped
exporting in the 2026-07-01 polite-client refactor. Nothing imported backfill
at test time, so fill_database.py step 3 -- the 3-year MTGTop8 backfill --
raised ImportError on every run for eleven weeks. This pins the import graph.
"""
import importlib
import pkgutil

import pytest

import scrapers

# Underscore-prefixed files in scrapers/ are one-off analysis scripts that run
# at import; only real modules are pinned here.
_MODULES = sorted(m.name for m in pkgutil.iter_modules(scrapers.__path__)
                  if not m.name.startswith("_"))


@pytest.mark.parametrize("name", _MODULES)
def test_scraper_module_imports(name):
    importlib.import_module(f"scrapers.{name}")


def test_backfill_exposes_run_backfill():
    from scrapers.backfill import run_backfill  # noqa: F401
