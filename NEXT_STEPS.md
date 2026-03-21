# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-03-21

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

## Phase 3: PyQt6 GUI — STABLE ✅

### What's built (as of 2026-03-21)

```
run_gui.py                       ✅ launcher (sets matplotlib QtAgg backend first)
launch_app.bat                   ✅ double-click to launch from Explorer
create_shortcut.bat              ✅ run once to put desktop shortcut in place
gui/theme.py                     ✅ design system + make_pip_widget() with QPainter circles
gui/fonts/Orbitron.ttf           ✅ bundled heading font
gui/main_window.py               ✅ 8 tabs (Ask Claude shown only if API key set)
gui/setup_wizard.py              ✅ first-time setup flow
gui/worker_threads.py            ✅ all worker threads
gui/widgets/chart_canvas.py      ✅ fetch_chart_data() + draw_from_data()
gui/widgets/meta_table.py        ✅
gui/widgets/archetype_detail.py  ✅ 4 tabs: Average Deck / Recent Lists / Tech Choices / Resources
gui/widgets/deck_export.py       ✅ MTGO/MTGA .txt export + decklist.org tournament sheet
gui/tabs/dashboard.py            ✅ Untapped.gg layout, trend color-coding, CSV export, dynamic titles
gui/tabs/deck_analyzer.py        ✅ Load avg deck, recommendations panel, Chapin tooltips, Export
gui/tabs/search.py               ✅ card images from Scryfall, click-to-detail in deck search
gui/tabs/charts.py               ✅ archetype autocomplete dropdown from DB
gui/tabs/predictions.py          ✅
gui/tabs/knowledge_base.py       ✅ add/browse bookmarks + guides table, Sync Guides button
gui/tabs/ask_claude.py           ✅ optional streaming chat (hidden until API key set in Settings)
gui/tabs/settings.py             ✅ formats, data window, auto-update, AI Assistant key section
gui/tray_icon.py                 ✅ system tray, status dots, right-click menu
gui/first_run_setup.py           ✅ one-time UAC wizard, registers all 3 tasks
scrapers/guides.py               ✅ imports Skill Issue Magic Google Sheet → guides table
```

### START HERE next session

```bash
python run_gui.py
# or double-click launch_app.bat / desktop shortcut
```

---

## Knowledge Base — COMPLETE ✅

| Feature | Status |
|---|---|
| `scrapers/guides.py` — imports 339 guides from Skill Issue Magic sheet | ✅ |
| `guides` table in DB | ✅ |
| `bookmarks` table in DB | ✅ |
| Knowledge Base tab — add/browse/delete bookmarks, Sync Guides button | ✅ |
| Resources tab in archetype detail — guides + bookmarks, clickable links | ✅ |

Re-sync guides any time:
```bash
python -m scrapers.guides
# or click "Sync Guides" in the Knowledge Base tab
```

---

## Ask Claude (optional AI chat) — COMPLETE ✅

- Hidden by default — appears in the tab bar only when an API key is set
- Configure: **Settings → AI Assistant → enter key → Save Settings**
- Key stored in `data/preferences.json` (gitignored — never committed)
- Injects live meta context (top archetypes, standings) from local DB
- Multi-turn streaming chat, `claude-opus-4-6` with adaptive thinking
- `anthropic` package: `pip install anthropic`

---

## Remaining features — pick up here

### A — User Preferences System (partially done)

Full spec in CLAUDE.md.

Still TODO:
1. **Format selection in setup wizard** — add page 0 before Scryfall download
   - Checkboxes: Standard (default on) / Pioneer / Modern / Legacy
   - Saves `preferences.json` immediately on Next
2. **`user_preferences` table in `db/database.py`** (or just keep using preferences.json)
3. **Wire scrapers** — `background_fill.bat` and `fill_database.py` skip unselected formats

### B — Charts compare mode

Overlay multiple archetype trend lines on one chart (multi-select archetype combo).

### C — PyInstaller packaging

```bash
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer" --add-data "gui/fonts;gui/fonts"
```
- `data/` stays external (DB + Scryfall bulk file too large to embed)
- Test on a clean machine without Python installed
- `anthropic` package should be optional (only needed if Ask Claude is used)

---

## Data status (as of 2026-03-21)

| Format | Events | Decks | Notes |
|---|---|---|---|
| Standard | 2,043+ | ~24,289+ | Nov 2024 – Mar 2026, daily 6 AM task active |
| Pioneer | 109 | 3,125 | MTGDecks 20-page scrape completed |
| Modern | scraping | TBD | Background scrape may still be running |
| Guides | 331 | — | Skill Issue Magic sheet, last synced 2026-03-21 |

---

## Known issues / notes

- **Pip circles** — QPainter.drawEllipse() confirmed rendering as proper circles ✅
- **Screenshots** — always use `python -c "import pyautogui; pyautogui.screenshot().save('data/gui_screenshot.png')"`. Never save to Windows Temp folder.
- `analysis/charts.py` sets `matplotlib.use("Agg")` at import — never import it inside GUI code. Use `gui/widgets/chart_canvas.py` instead.
- `data/scryfall_oracle.json` is ~162 MB and gitignored. Regenerate: `python -m scrapers.scryfall --download`
- MTGDecks scraper uses `cloudscraper`. If 403s return: `pip install --upgrade cloudscraper`
- VS Code default terminal is **cmd** (not Git Bash). New terminals open in cmd.
- After any new backfill/scrape, enrich new cards: `python -m scrapers.scryfall`
- `exports/` folder is gitignored — created automatically on first export.
- `data/preferences.json` is gitignored — contains API key and user prefs.
