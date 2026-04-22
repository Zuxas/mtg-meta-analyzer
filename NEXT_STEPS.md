# NEXT_STEPS.md — Pick up here next session

Last updated: 2026-04-21

---

## OPEN PRIORITIES

### Deck Intelligence (remaining)
- [ ] Meta clustering by playstyle

### Query & Discovery
- [x] Card-name decklist search (Deck Search → Cards filter, AND + OR)
- [ ] Global "All Formats" option everywhere

### Sim Integration (mostly done)
- [x] Standard-format support in SIMULATE + CALIBRATION (format dropdowns)
- [x] Cross-tab format_hint plumbing (Deck Analyzer / Search / Dashboard / My Decks)
- [x] Match Log right-click "Simulate this matchup" with fuzzy lookup
- [x] Field gauntlet Top-N (All/5/8/10) slice by meta share
- [x] Sim run history (last 10 runs)
- [ ] Goldfish APLs for Standard archetypes (cross-repo mtg-sim work)

### Match Logging Enhancements
- [x] Record by event type, trend chart, SB Advice (matchup_advisor)
- [x] Card swap rationale tracker (swap_notes + swap_verdict columns + Swap indicator)

### Testing & Iteration
- [x] Matchup hypothesis tracker (Tournament → Hypotheses sub-tab)

### Tournament System
- [x] Pre-event prep checklist (Tournament → Prep Checklist sub-tab)
- [x] Generate Prep Package HTML export (Event Optimizer button)
- [ ] Round tracking during event
- [ ] Post-event analysis (expected vs actual matchups)

### UI/UX (audit rollout)
- [x] Hardcoded color audit — theme.* constants + helpers
- [x] Spacing scale (SPACE_XS/SM/MD/LG/XL on 4px grid)
- [x] empty_state_label() helper + My Decks wire
- [x] h1/h2/h3 style helpers
- [x] Dense control bars grouped (Dashboard separators + Event Optimizer QGroupBoxes)
- [x] Dialog size tiers (DIALOG_SM/MD/LG)
- [x] QtAwesome icons on primary actions
- [x] StatusRow helper (simulate/calibration/event_optimizer)
- [x] Deck legality watchdog (My Decks Legal column)
- [x] Card inclusion trend sparkline (Card Browser)
- [x] Similar-scraped-decks panel w/ clickable rows
- [ ] Interaction speed (filters update in place)
- [ ] Dashboard + Heatmap empty-state polish

### Packaging
- [ ] PyInstaller .exe packaging + clean machine testing

---

## RECENTLY COMPLETED (2026-04-08)

### Deck Intelligence System
- [x] Card adoption tracking (analysis/card_adoption.py) — week-by-week inclusion rates
- [x] Baseline vs deviation — Deck Analyzer compares your list vs average deck
- [x] Slot analysis (analysis/slot_analysis.py) — role, trend, substitutes, competitors
- [x] Deck recommendation engine (analysis/deck_recommender.py) — "Best Deck" button on Dashboard
- [x] Deck role classification (analysis/deck_roles.py) — Aggro/Midrange/Control/Combo/Tempo on Dashboard

### Meta & Data
- [x] Meta change detection (analysis/meta_change.py) — Dashboard "Meta Shift" upgraded
- [x] Cross-source duplicate detection (analysis/cross_source_dedup.py) — Settings "Scan Duplicates"
- [x] Personal WR vs meta expected — already implemented in Match Log

### Codebase Consolidation
- [x] Phase 1: scrapers/constants.py, db/helpers.py, gui/worker_utils.py, gui/widgets/table_helpers.py
- [x] Phase 2: tournament_prep.py split (1,626→136+486+1,038), win_rates.py split (1,407→1,116+125+188)
- [x] Docs: CLAUDE.md 680→330 lines, NEXT_STEPS.md 725→53, ROADMAP.md 165→101
- [x] Root scripts moved to scripts/

### UX Improvements
- [x] Tab consolidation: 13→7 (Dashboard, Meta, Decks, Search, Tournament, Resources, Settings)
- [x] Tab tooltips on all tabs
- [x] Empty states with helpful guidance (Match Log, Heatmap)
- [x] friendly_error() — 30+ error sites now show user-friendly messages
- [x] Indeterminate progress bars on Heatmap + Event Optimizer

### UI/UX Overhaul + Branding (2026-04-07)
- [x] Inter font, near-black theme, Team Resolve logo everywhere
- [x] Chart readability subtitles, event peers, flex slots, team notes
