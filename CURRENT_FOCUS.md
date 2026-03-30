# CURRENT_FOCUS.md

> Tracks which system is actively being developed.
> Update this at the start of each session.
> Last updated: 2026-03-27

---

## Current Status: APP STABLE — NO ACTIVE DEVELOPMENT SPRINT

The MTG Meta Analyzer is feature-complete for the current scope.
All major systems are built and working. Daily scrapers are running.

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

## Only remaining item

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
