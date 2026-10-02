# Melee match gap — diagnosis, fixes and targeted backfill (2026-10-01)

Branch `fix/melee-match-gap-2026-10-01` (from `ee392b6`). Handoff:
`harness/inbox/mtg-meta-analyzer/2026-10-01_melee_match_gap_handoff.md`.

## Root causes

| # | Symptom | Root cause (evidence) | Fix |
|---|---|---|---|
| 1 | Melee `matches` stopped at 2026-09-13 (modern / standard / legacy) | TournamentSearch **snaps `start` down to a multiple of `length`** (offset = start // length * length; 6/6 predictions matched live; repeated identical requests returned identical ids / dates / `recordsTotal` = 1,151 -- paging is deterministic, not unstable). The scraper requested start = total − 100·(page+1) = 1051, was served rows 1000-1099 and never saw the newest `total % 100` rows. | Page-aligned walk back from the last page; dedup by id; newest first; one re-read of the newest page if `recordsTotal` moves (≤ pages + 2 requests). |
| 2 | "No started rounds" for SCG 442749 (Dallas $1K RCQ, 197p) | Not a markup change: 442749 is a **registration shell** whose public page has no pairings section; the event was split into **FLIGHT A (462365, 103p) / FLIGHT B (462366, 102p)**, which use the normal round markup and were lost to cause 1. Modern+ side events 442783 / 442838 / 445523 publish no pairings at all. | Round parsing scoped to `#pairings-round-selector-container` (unstarted rounds never admitted) with an explicit `no-pairings-section` diagnosis. |
| 3 | Empty-looking `-- MTGMelee --` sections in `logs/background_fill.log` | Parent `print()` block-buffered under redirection while the child writes directly to the file → child output landed above all headings (reproduced). | Headings / warnings flushed before the child runs. |
| 4 | `sqlite3.IntegrityError: FOREIGN KEY constraint failed` (deck_cards insert) | `db/maintenance.py` archiving, unrelated to Melee: active card id 8226397 'Secrets of the Key' already archived as 1565854; `INSERT OR IGNORE INTO cards (id, name)` was ignored on `UNIQUE(name)` and the deck_cards row referenced a missing card. Pioneer archiving aborted on every run. | Archive ids resolved by natural key (card name; event source key; deck key). |
| 5 | (found during the backfill check) wrong archetype labels | `_map_archetype` called `normalize(deck_name, fmt)`: the format string landed in the positional `fuzzy` parameter, so every Melee scrape fuzzy-guessed labels -- wrongly and unstably ('Mono-Green Broodscale' → 'Mono Red Aggro'; 'Mono-Red Ruby Storm' → 'Cycle Storm' / 'Poison Storm'). | Exact canonical / alias only, else the published name; junk aliases ('Decklist') unlabelled. User decision: fix, then backfill. |

## Backfill (targeted, idempotent)

Backup: `E:\mtg-data\mtg_meta.backup-2026-10-01-pre-melee-backfill.db` (SQLite online backup API,
437,960,704 bytes), `PRAGMA integrity_check` = `ok`. No fill job was running (tasks idle, no scraper
processes).

| Event | Date | Players | Pairings | Decided | Storable | Before | Inserted | Re-run inserted |
|---|---|---|---|---|---|---|---|---|
| 448946 Modern Apocalypse | 2026-09-19 | 34 | 102 | 102 | 78 | 0 | **78** | 0 |
| 442749 Dallas $1K RCQ (shell) | 2026-09-04 | 197 | 0 | 0 | 0 | 0 | 0 | -- |
| 462365 FLIGHT A (Dallas RCQ) | 2026-09-04 | 103 | 280 | 280 | 19 | 0 | **19** | 0 |
| 462366 FLIGHT B (Dallas RCQ) | 2026-09-04 | 102 | 272 | 272 | 7 | 0 | **7** | 0 |
| 451148 China Open S13 RC | 2026-09-12 | 403 | 1,379 | 1,379 | 1,364 | 0 | **1,364** | 0 |
| 467590 / 467594 Vancouver RCQs | 09-19 / 09-20 | 47 / 39 | 120 / 104 | 120 / 104 | 0 / 0 | 0 | 0 (not run) | -- |

Total +1,468 rows (live `matches` 330,584 → 332,052; Modern melee 113,616 → 115,084). Every new row:
correct date, format `modern`, source `mtgmelee`; 0 duplicate keys; 0 blank archetypes; 0 winner /
result inconsistencies. Live `PRAGMA integrity_check` = `ok`. Vancouver events stay absent (every deck
name blank -- decklists not published).

Mapping (451148): 2,758 deck slots of decided matches -- 30 blank, 1,926 labels already present in the
stored Modern vocabulary, 802 new published labels (e.g. 'Mono Green Broodscale', 'Abzan Devoted Druid
Combo', 'Mono Green Eldrazi Broodscale', vague ones such as 'Izzet' / 'Boros'); one non-English label
('无色', 8 slots) stored verbatim. Flights: most decks published blank (437 / 433 blank slots), hence 19 / 7.

## Open follow-ups
- Rows stored before 2026-10-01 keep their fuzzy labels (6,440 Modern melee rows 'Mono Red Aggro',
  315 'Decklist'); relabeling needs the raw published names -> re-scrape + rewrite behind a backup.
- Newly discoverable events not in this targeted scope (e.g. 'Autumn Modern Championship',
  'NM2026 - Norgesmesterskapet') will be picked up by the scheduled job once this branch is live.
