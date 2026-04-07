# CURRENT_FOCUS.md

> Tracks which system is actively being developed.
> Update this at the start of each session.
> Last updated: 2026-04-06

---

## Current Status: ACTIVE SPRINT — Advanced Analytics Integration

Integrating external algorithms and data sources from the MTG GitHub ecosystem
into the existing app. Six-phase plan, building in dependency order.

---

## What's fully built and stable

| System | Status |
|---|---|
| Data Engine | COMPLETE — MTGTop8, MTGDecks, MTGMelee scrapers; 262k+ matches; daily tasks |
| Query Engine | COMPLETE — CLI + GUI query interface, URL import, all subcommands |
| Deck Intelligence | COMPLETE — Blunder detection, Chapin eval, avg deck, legality checker |
| Testing System | COMPLETE — My Decks tab, sideboard plans, Event Optimizer, Breaker Math |
| Tournament System | COMPLETE — Event Optimizer with G1/G2G3, flip detection, RC math |
| User Preferences | COMPLETE — Format selection in wizard + settings, preferences.json drives all scrapers |
| GUI | COMPLETE — 10 tabs, system tray, first-run UAC wizard, card image tooltips |

---

## Advanced Analytics Sprint: ALL 6 PHASES COMPLETE

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Prep Priority + Trap Detection | DONE — `analysis/meta_scoring.py`, Dashboard Prep/Status columns |
| 2 | Glicko-2 Power Ratings | DONE — `analysis/ratings.py`, Dashboard Rating column with tooltips |
| 3 | Nash Equilibrium + RPS Cycles | DONE — `analysis/equilibrium.py`, Heatmap Equilibrium button/dialog |
| 4 | Card Text Embeddings | DONE — `analysis/card_embeddings.py`, Card Browser "Similar Cards" |
| 5 | Co-occurrence Embeddings (Card2Vec) | DONE — `analysis/cooccurrence_embeddings.py`, Card Browser "Functional Substitutes" |
| 6 | KNN Archetype Classifier | DONE — `analysis/knn_classifier.py`, Deck Analyzer auto-detect archetype |

---

## Also deferred

**PyInstaller .exe packaging** — intentionally deferred until app stabilizes further.
Do NOT start this until explicitly requested.

```bash
# When ready:
pip install pyinstaller
pyinstaller --onefile --windowed run_gui.py --name "MTG Meta Analyzer" \
  --add-data "gui/fonts;gui/fonts"
```

---

## If starting a new session with no specific task

1. Run `python run_gui.py` and verify the app launches cleanly
2. Check `logs/background_fill.log` for any scraper errors from the last daily run
3. If scraper errors: fix the specific error, don't rebuild what's working
4. If no errors: look at NEXT_STEPS.md for any lower-priority items

---

## Active competitive context (Jermey / Zuxas / Team Resolve)

- Format: Modern, current RC season
- Decks in testing: Boros Energy, UW Blink, Jeskai Blink, Grixis Reanimator (Glockulous), UW Control, Prowess
- Career: 5 RC qualifications — goal is Pro Tour conversion
- The MTG Meta Analyzer exists to support this competitive work, not as a standalone project
