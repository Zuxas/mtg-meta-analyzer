# Claude Code prompt — data pipeline fixes (2026-09-20)

Three defects found while investigating why Modern data stopped in June. The
first is already fixed in config; the other two are code. Do them in order —
Bug 2 currently blocks any full rebuild.

---

## Bug 1 — silent format default (config fixed, code still needs work)

`scripts/run_fill_from_prefs.py::load_formats()`:

```python
fmts = prefs.get("formats", [])
if fmts:
    return fmts
...
return ["standard"]
```

`data/preferences.json` had **no top-level `formats` key** — only `ui_state`.
No exception is raised, so the `[warn] Could not read preferences` branch never
fired; it silently returned `["standard"]`. Legacy and Pauper kept flowing only
because of `_MELEE_ALWAYS = ["legacy", "pauper"]`.

Result: Modern and Pioneer were excluded from every scrape for ~10 weeks while
the log printed `[prefs] Active formats: standard`, which reads like a choice.

**Already done:** `formats: ["modern","standard","pioneer","legacy","pauper"]`
written to `data/preferences.json` (backup alongside as `.bak-<stamp>`).
`load_formats()` now returns all five and `melee_formats` dedupes correctly.

**Still to fix in code:**

1. Distinguish *configured* from *defaulted*. When the key is missing, print
   `[prefs] No 'formats' key in preferences.json — DEFAULTING to standard only.
   Modern/Pioneer will not be scraped.` A fallback must never look like a setting.
2. `fill_database.py::_load_formats()` is a near-duplicate of
   `run_fill_from_prefs.py::load_formats()` with a different default
   (`prefs.get("formats", ["standard"])` vs `[]`). Two copies of the same
   decision drift. Move one implementation into `db/helpers.py` and import it
   in both.
3. Make the GUI write `formats` on save. If a Settings format picker exists and
   only persists to `ui_state`, that is how the key went missing in the first
   place — find it and fix the write path, or the same bug returns.
4. Test: missing key, empty list, malformed JSON, and a valid list — assert the
   defaulted cases emit the loud warning.

---

## Bug 2 — Scryfall bulk API changed shape (blocks `fill_database.py`)

`scrapers/scryfall.py::download_bulk_data()` line ~140 raises
`KeyError: 'download_uri'`. This is a **fatal** exception inside
`fill_database.py` step 2, so steps 3–6 — including the 3-year MTGTop8
backfill — never run. It is also the cause of the
`-- Scryfall enrichment --  [warn] exited with code 1` line appearing daily in
`logs/background_fill.log`.

Scryfall now returns (verified live, 2026-09-20, `GET https://api.scryfall.com/bulk-data`):

```json
{
  "type": "oracle_cards",
  "updated_at": "2026-09-20T09:01:59.187+00:00",
  "uri": "https://api.scryfall.com/bulk-data/27bf3214-...",
  "jsonl_download_uri": "https://data.scryfall.io/oracle-cards/oracle-cards-20260920090159.jsonl.gz",
  "compressed_size": 24706130
}
```

Every one of the 7 entries now carries exactly:
`compressed_size, description, id, jsonl_download_uri, name, object, type, updated_at, uri`.

So **`download_uri` and `size` are gone**, and the payload is now
**gzipped JSONL**, not a JSON array.

`data/scryfall_oracle.json` is a 201 MB JSON array last downloaded
**2026-07-26** (see `data/scryfall_meta.json`) — card data is ~8 weeks stale,
which matches when the API changed.

**Implement.** Keep the on-disk format a JSON array so nothing downstream
changes — decompress and convert at download time. Do not refactor
`get_cards_data()` / `enrich_cards()` into a JSONL reader; that is a much
larger blast radius for no benefit.

1. Read `jsonl_download_uri`, falling back to `download_uri` if present, and
   raise a clear error naming the available keys if neither is.
2. Use `compressed_size` for the progress display, falling back to `size`.
3. Stream the `.gz`, decompress with `gzip.GzipFile` over the raw stream, parse
   one JSON object per line, and write a single JSON array to `BULK_PATH`.
   Write to `BULK_PATH + ".tmp"` and `os.replace()` on success so a failed
   download cannot leave a truncated 200 MB file where a valid one was.
4. Record `source_url` and `downloaded_at` in `BULK_META_PATH` as today.
5. In `fill_database.py::main()`, wrap `step_scryfall_download()` in
   try/except so a Scryfall outage degrades to a warning instead of killing
   the backfill. It is an enrichment step, not a prerequisite.
6. Tests: a fake index with only `jsonl_download_uri`, one with only the legacy
   `download_uri`, one with neither (expect the clear error), and a gz-JSONL
   fixture round-tripping to a JSON array.

---

## Bug 3 — per-format freshness guard

Already specified as Task 1 in `docs/prompts/CHAPIN_METRICS.md`. The Bug 1
diagnosis is the argument for it: a global `last_status: ok` with a stale
per-format reality is exactly what hid this for ten weeks. Also covers the
mixed date formats (`matches.event_date`: 293,078 ISO vs 10,266 `dd/mm/yy`;
`events.date`: 2,131 vs 4,208).

---

## Verification

`python scripts/data_health_report.py --freshness-only` should show all five
formats current. Then `python -m scrapers.mtgmelee_scraper --counts`.

Per the repo rules: update `CLAUDE.md`, `NEXT_STEPS.md`, `ROADMAP.md`, run
`pytest`, then `git push`. After any scraper change verify with `--counts`
rather than trusting the exit code — the exit code is what lied here.
