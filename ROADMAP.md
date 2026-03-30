# ROADMAP.md — MTG Meta Analyzer Feature Roadmap

> Last updated: 2026-03-27

---

## 1. DATA ENGINE (Priority: Immediate)

- [x] Memory/resource leak audit and fix (2026-03-26 — all workers, DB conns, app exit cleanup)
- [x] Real match W/L pipeline — MTGMelee scraper + matches table + dashboard ★ badges (complete)
- [x] MTGMelee scraper rewritten for new API endpoints (2026-03-25) — 250 Standard tournaments scraped
- [x] Dedup-aware trend denominator in `get_archetype_trend()` (2026-03-25)
- [x] User Preferences System — format selection wired end-to-end (2026-03-27)
      Setup wizard page 0 (format checkboxes, saves preferences.json immediately)
      fill_database.py reads preferences via _load_formats() — no more hardcoded format lists
      scripts/run_fill_from_prefs.py reads preferences and runs scrapers for selected formats only
      background_fill.bat delegates to run_fill_from_prefs.py instead of hardcoded per-format commands
- [ ] Cross-source duplicate detection with confidence scoring
- [ ] Manual force scrape button with progress display
- [x] Data normalization: 170+ aliases, WUBRG codes, apostrophe fix, junk exclusion, backfill (2026-03-26)
- [x] Unicode crash fix in MTGTop8 scraper — PYTHONIOENCODING=utf-8 (2026-03-26)
- [x] Meta standings fallback to matches table when decks data is stale (2026-03-26)
- [x] Legacy + Pauper format support in MTGMelee scraper + heatmap (2026-03-26)
- [ ] Meta change detection (compare two time periods)

---

## 2. QUERY & DISCOVERY ENGINE (Priority: Near-term)

- [ ] Card-name decklist search (exact + multi-card AND/OR)
- [ ] Global "All Formats" option everywhere
- [x] URL import in Deck Analyzer (Moxfield, Archidekt, MTGGoldfish, MTGTop8) (2026-03-26)
- [ ] Event peer navigation (all decks from same event)
- [ ] Flex slot competition view (cards competing for same slot)

---

## 3. DECK INTELLIGENCE SYSTEM (Priority: Near-term)

- [ ] Card adoption & progression tracking over time
- [ ] Baseline vs deviation comparison (user list vs stock)
- [ ] Deck role classification (proactive/reactive/combo/tempo)
- [ ] Meta clustering by playstyle
- [ ] Meta-based deck recommendation engine
- [ ] "Why this card?" slot analysis
- [ ] Hypergeometric encounter probability in Event Optimizer
- [x] Event type presets (RCQ/RC/PTQ/Custom), x-loss cutoff, day-2 conversion math (2026-03-26)

---

## 4. TESTING & ITERATION SYSTEM (Priority: Medium-term)

- [ ] Match logging (opponent arch, result, play/draw, notes) — personal match tracker
- [ ] Card swap rationale tracker (why you changed cards)
- [ ] Matchup hypothesis tracker (record + validate theories)
- [x] Sideboard planning system DB backend — `db/saved_decks.py` created 2026-03-25 (`saved_sb_plans` table with play/draw IN/OUT, difficulty, upsert)
- [x] My Decks GUI tab — `gui/tabs/my_decks.py` (2026-03-26)
- [ ] Gauntlet builder (auto top decks to test against)
- [ ] Test recommendation engine
- [ ] Testing insights from logged matches

---

## 5. TOURNAMENT SYSTEM (Priority: Medium-term)

- [ ] Pre-event prep mode (deck + SB guide + expected meta)
- [ ] Round tracking during event
- [ ] Post-event analysis (expected vs actual matchups)
- [ ] Blocking/teammate support math

---

## 6. UI/UX SYSTEM (Ongoing)

- [x] Dashboard Meta Impact bar — shows dedup filter rows removed + most affected archetypes (2026-03-25)
- [x] Dashboard worker lifecycle fix — Refresh button crash resolved (2026-03-25)
- [x] My Decks GUI tab — list/add/edit/delete saved decks + SB plans (2026-03-26)
- [x] Charts Compare Mode — multi-archetype trend overlay (2026-03-26)
- [x] Legend/key for dashboard tier badge colors (S/A/B/C) and ★ star suffix — tooltip on Tier header (2026-03-25)
- [x] Heatmap rewrite: combined real+scraped data, Overall WR column, source indicators, data-density fallback (2026-03-26)
- [x] Dashboard daily granularity toggle, format event markers on charts (2026-03-26)
- [x] Win rate smoothing (3-point rolling avg, min 3 appearances/week) (2026-03-26)
- [x] Default top 8 by appearances in chart checkboxes (2026-03-26)
- [x] SB plan CRUD dialog in My Decks tab (2026-03-26)
- [x] "This List" tab in archetype detail for exact decklists from Recent Top Finishes (2026-03-26)
- [x] Sparklines on Popular panel — 4-week trend mini chart per archetype (2026-03-26)
- [x] Layout consistency pass — tab margins standardized to 8px (2026-03-26)
- [x] Heatmap sticky headers — replaced QScrollArea with direct QTableWidget (2026-03-26)
- [x] Card image tooltips — Scryfall API, in-memory cache, custom floating widget (2026-03-26)
- [x] URL import in Deck Analyzer — Moxfield, Archidekt, MTGGoldfish, MTGTop8 (2026-03-26)
- [x] Knowledge Base filters — format/archetype dropdowns, comment text search (2026-03-26)
- [x] Archetype normalization — 250+ aliases across all 5 formats, junk exclusion (2026-03-26)
- [ ] Quick-glance summary bar at top of each tab
- [ ] Chart readability (always show sample size + timeframe)
- [ ] Interaction speed (filters update in place)

---

## 7. FORMAT EXPANSION (Low priority)

- [x] Legacy support: 25,304 matches from 86 tournaments, MTGTop8 scraper active (2026-03-26)
- [x] Pauper support: 16,174 matches from ~130 tournaments, daily scrapes active (2026-03-26)
- [ ] Premodern support
- [ ] Format-specific banned lists + archetype dictionaries

---

## 8. ADVANCED FEATURES (Phase 4)

### Match Logging (personal results)
- [x] Basic match logging — opponent deck, W/L/D, play/draw, game-by-game, notes (2026-03-29)
- [ ] Compare personal WR vs meta expected WR per matchup
- [ ] Track record by event type (RCQ vs Open vs RC)
- [ ] Trend analysis: personal WR over time, improving/declining matchups
- [ ] Integration with SB advisor: "your WR is low vs X, adjust your plan"

### New Set Break Protocol
- [ ] "Set Analysis" tool: paste new set card list
- [ ] AI classification of each card into buckets:
    Rate Outliers / Engine Pieces / Enablers / SB Breakers / Upgrade Cards
- [ ] For each top meta archetype, flag which new cards slot in and why
- [ ] Output: ranked "most likely to matter" list with reasoning
- [ ] Uses Claude API (Ask Claude tab infrastructure) for classification

### Team Collaboration
- [ ] Export/import gauntlet results as JSON (share on Discord)
- [x] Export/import SB plans + decklist as JSON — Share JSON / Import JSON buttons in My Decks (2026-03-30)
- [ ] Team notes field on matchup heatmap cells
- [ ] No server needed — file-based import/export only
