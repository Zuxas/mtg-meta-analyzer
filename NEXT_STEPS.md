# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-03-20

---

## Phase 2: Core Analysis — COMPLETE

All backend modules done. Do not rebuild any of these.

| Module | Command |
|---|---|
| Archetype normalization (migration applied) | `python -m analysis.archetypes --apply` |
| MTGDecks.net scraper (cloudscraper) | `python -m scrapers.mtgdecks --pages 3` |
| Trend charts (meta share, trend, heatmap) | `python -m analysis.query chart meta` |
| Prediction logging + validation | `python -m analysis.query predict` |
| Blunder Detection (Major/Moderate/Minor) | `python -m analysis.query blunder "Deck"` |
| Chapin Principles (6 scored principles) | `python -m analysis.query chapin "Deck"` |

---

## Phase 3: PyQt6 GUI — IN PROGRESS

### What's built (as of 2026-03-20)

All GUI skeleton files exist and import cleanly. Backend wired up.

```
run_gui.py                  ✅ launcher (sets matplotlib QtAgg backend first)
gui/__init__.py             ✅
gui/main_window.py          ✅ dark palette, 5 tabs, setup wizard check, background scrape
gui/setup_wizard.py         ✅ first-time setup: Scryfall download + backfill + event counter
gui/worker_threads.py       ✅ ScryfallDownloadWorker, BackfillWorker, QuickScrapeWorker, DataLoadWorker
gui/widgets/__init__.py     ✅
gui/widgets/chart_canvas.py ✅ FigureCanvasQTAgg — plot_meta_share/plot_trend/plot_heatmap
gui/widgets/meta_table.py   ✅ QTableWidget with archetype_selected signal
gui/tabs/__init__.py        ✅
gui/tabs/dashboard.py       ✅ Table + chart, format/weeks/top-N controls, row-click → trend
gui/tabs/deck_analyzer.py   ✅ Arena paste → Blunder + Chapin analysis
gui/tabs/search.py          ✅ Card lookup, deck search (SQL), head-to-head
gui/tabs/charts.py          ✅ Interactive controls + live chart canvas + Save PNG
gui/tabs/predictions.py     ✅ Generate/validate/view predictions + accuracy summary
```

### START HERE next session — run the GUI and fix any runtime issues

```bash
python run_gui.py
```

Expected on first run: setup wizard (if DB < 50 events).
Expected on returning run: dashboard loads automatically, background scrape runs.

### Known things to test / likely issues

1. **Setup wizard Scryfall step** — subprocess output parsing may need tuning if
   the download progress output format changed. If the bar stays at 0%, check
   `scrapers/scryfall.py --download` stdout output and adjust `ScryfallDownloadWorker`.

2. **Chart canvas sizing** — heatmap figure size recalculates dynamically but may
   need `self._canvas.updateGeometry()` or a `draw_idle()` call after resize.

3. **Deck Analyzer legality check** — `analyze_deck()` calls `get_cards_data()`
   which uses the Scryfall local cache. If `data/scryfall_oracle.json` is missing,
   legality check raises. The `--no-legality` flag in the CLI bypasses this.
   Add a try/except in `_AnalyzeWorker.run()` around the legality check if needed.

4. **search_local() return format** — `card.get("legalities")` may be a JSON string
   (stored as TEXT in SQLite). The search tab already has a `json.loads` fallback.

5. **predictions `accuracy_report()`** — returns `{}` or `None` if no predictions
   exist yet. The tab handles this gracefully but verify on fresh DB.

### Next features after basic run is stable

#### A — First-run data quality
- After setup wizard completes, auto-run `python -m analysis.archetypes --apply`
  to normalize any newly scraped archetype names
- Add a "Normalize Archetypes" button to main window menu bar

#### B — Dashboard improvements
- Add "Last N weeks" summary chip below chart (e.g. "Izzet Prowess: +2.3% meta share")
- Color-code table rows: green = rising, red = falling vs prior 2 weeks
- Export table as CSV button

#### C — Charts tab polish
- Auto-populate archetype autocomplete from DB (`get_meta_standings` result)
- "Compare archetypes" mode: overlay multiple trend lines on one chart

#### D — Deck Analyzer improvements
- "Load Average Deck" button: populate the text box with the average deck for
  a selected archetype (calls `get_average_deck()`)
- Show Chapin explanation text per principle (already in `PrincipleScore.explanation`)

#### E — Packaging
Once GUI is stable and tested:
```bash
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer"
```
- `data/` stays external (DB + Scryfall bulk file too large to embed)
- Include `README_INSTALL.txt` explaining where to place data files
- Test on a clean machine without Python installed

---

## Data status (as of 2026-03-20)

| Source | Events | Decks |
|---|---|---|
| MTGDecks.net (latest scrape) | 29 new | 3,190 |
| Notable events | RC Turin 2026 (1,025p), TMNT Spotlight (673p), Champions Cup Final (384p), ANZ Super Series (208p) |

Total Standard events in DB: 1,564

---

## Known issues / notes

- `analysis/charts.py` sets `matplotlib.use("Agg")` at import — never import it
  inside GUI code. Use `gui/widgets/chart_canvas.py` instead.
- `data/scryfall_oracle.json` is ~162 MB and gitignored. Regenerate:
  `python -m scrapers.scryfall --download`
- MTGDecks scraper uses `cloudscraper`. If 403s return:
  `pip install --upgrade cloudscraper`
- Blunder/Chapin on average decks may show <60 cards (inclusion threshold) — expected.
- After any new backfill/scrape, enrich new cards:
  `python -m scrapers.scryfall`
