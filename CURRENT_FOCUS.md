# CURRENT_FOCUS.md

> Tracks which system is actively being developed.
> Update this at the start of each session.

---

## Active System: DATA ENGINE

**Why this first:**
The Data Engine is the foundation everything else depends on.
A memory leak crashed the app overnight, the MTGMelee scraper needs fixing,
and duplicate/normalization quality directly affects every downstream analysis.
Stability here unlocks reliable work on all other systems.

## Immediate tasks (in order)

1. **Memory leak audit** — CRITICAL
   - Suspects: QuickScrapeWorker not being garbage collected, FigureCanvasQTAgg
     retaining references, DB connections not closed on thread exit
   - Goal: app runs overnight without crash

2. **MTGMelee scraper fix**
   - Run `--test --verbose`, confirm 200 OK response shape
   - Fix field mapping / endpoint params based on actual response
   - Validate with `--format standard --pages 2`

3. **Cross-source duplicate detection** (after #1 and #2 stable)
   - Extend `analysis/archetypes.py` `find_card_based_duplicates()`
   - Add confidence score to each pair (name similarity + card overlap %)
   - Surface in GUI for manual review

## Next system after Data Engine

**Query Engine** — card-name decklist search, URL import, All Formats option

---

## System status

| System | Status |
|---|---|
| Data Engine | ACTIVE — in progress |
| Query Engine | QUEUED |
| Deck Intelligence | STABLE — no active work |
| Testing System | PLANNED — no code yet |
| Tournament System | STABLE — no active work |
