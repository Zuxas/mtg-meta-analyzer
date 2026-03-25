# Tournament System

## Purpose
Everything that helps you prepare for and navigate a live tournament event.
Combines meta knowledge, deck intelligence, and real-time round tracking.

## Responsibilities
- RCQ Optimizer: binomial top-cut probability, field grade, matchup breakdown
- Breaker Math: real-time W/L/D tracker, ID calculator, draw equity, pair-down warning
- Pre-event prep mode: deck + SB guide + expected meta snapshot
- Round tracking during the event
- Post-event analysis: expected vs actual matchup distribution
- Blocking/teammate support math

## Current file ownership (existing code — not moved yet)

| File | Role |
|---|---|
| `analysis/tournament.py` | `rcq_equity()`, `binomial_top_cut()`, guide-aware post-board WR |
| `gui/tabs/tournament_prep.py` | RCQ Optimizer + Breaker Math UI (two sub-tabs) |

## Planned features (from ROADMAP)
- Pre-event prep mode (deck + SB guide + expected meta)
- Round tracking during event
- Post-event analysis (expected vs actual matchups)
- Blocking/teammate support math
