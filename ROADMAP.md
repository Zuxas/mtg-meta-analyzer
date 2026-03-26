# ROADMAP.md — MTG Meta Analyzer Feature Roadmap

> Last updated: 2026-03-26

---

## 1. DATA ENGINE (Priority: Immediate)

- [x] Memory/resource leak audit and fix (2026-03-26 — all workers, DB conns, app exit cleanup)
- [x] Real match W/L pipeline — MTGMelee scraper + matches table + dashboard ★ badges (complete)
- [x] MTGMelee scraper rewritten for new API endpoints (2026-03-25) — 250 Standard tournaments scraped
- [x] Dedup-aware trend denominator in `get_archetype_trend()` (2026-03-25)
- [ ] Cross-source duplicate detection with confidence scoring
- [ ] Manual force scrape button with progress display
- [ ] Data normalization improvements
- [ ] Meta change detection (compare two time periods)

---

## 2. QUERY & DISCOVERY ENGINE (Priority: Near-term)

- [ ] Card-name decklist search (exact + multi-card AND/OR)
- [ ] Global "All Formats" option everywhere
- [ ] URL import in Deck Analyzer (Moxfield, Archidekt, MTGGoldfish, MTGTop8, MTGMelee)
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
- [ ] Hypergeometric encounter probability in RCQ Optimizer

---

## 4. TESTING & ITERATION SYSTEM (Priority: Medium-term)

- [ ] Match logging (opponent arch, result, play/draw, notes) — personal match tracker
- [ ] Card swap rationale tracker (why you changed cards)
- [ ] Matchup hypothesis tracker (record + validate theories)
- [x] Sideboard planning system DB backend — `db/saved_decks.py` created 2026-03-25 (`saved_sb_plans` table with play/draw IN/OUT, difficulty, upsert)
- [ ] Sideboard planning GUI — `gui/tabs/my_decks.py` (next up)
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
- [ ] My Decks GUI tab — list/add/edit/delete saved decks + SB plans (`gui/tabs/my_decks.py`)
- [x] Legend/key for dashboard tier badge colors (S/A/B/C) and ★ star suffix — tooltip on Tier header (2026-03-25)
- [ ] Layout consistency (global filters top, nav left, data center, detail right)
- [ ] Sticky headers + sortable columns everywhere
- [ ] Sparklines + trend arrows on meta table
- [ ] Quick-glance summary bar at top of each tab
- [ ] Chart readability (always show sample size + timeframe)
- [ ] Interaction speed (filters update in place)

---

## 7. FORMAT EXPANSION (Low priority)

- [ ] Pauper, Legacy, Premodern support
- [ ] Format-specific banned lists + archetype dictionaries
