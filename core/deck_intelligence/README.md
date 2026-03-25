# Deck Intelligence System

## Purpose
Everything that evaluates, scores, and reasons about a specific decklist.
Takes a 75-card deck as input and produces actionable insight.

## Responsibilities
- Deck construction scoring (land count, curve, color consistency, threats)
- Chapin Principles evaluation (6 weighted principles, 0-10 scored)
- Sideboard guide parsing and post-board win rate modeling
- Flip detection (matchups that reverse post-board)
- Card adoption and progression tracking over time
- Baseline vs deviation comparison (user list vs stock archetype)
- "Why this card?" slot analysis

## Current file ownership (existing code — not moved yet)

| File | Role |
|---|---|
| `analysis/blunders.py` | Deck scoring: Major/Moderate/Minor blunder detection |
| `analysis/chapin.py` | Chapin Principles (6 principles, weighted 0-10) |
| `analysis/sideboard_guides.py` | Guide parsing, G2/G3 WR model, flip analysis |

## Planned features (from ROADMAP)
- Card adoption & progression tracking over time
- Baseline vs deviation comparison (user list vs stock)
- Deck role classification (proactive/reactive/combo/tempo)
- Meta clustering by playstyle
- Meta-based deck recommendation engine
- "Why this card?" slot analysis
- Hypergeometric encounter probability in RCQ Optimizer
