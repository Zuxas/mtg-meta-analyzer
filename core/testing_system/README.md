# Testing & Iteration System

## Purpose
Everything that helps you learn from your own play sessions and improve over time.
Connects real match outcomes back to deck decisions.

## Responsibilities
- Match logging (opponent archetype, result, play/draw, notes)
- Card swap rationale tracker (why you changed cards between sessions)
- Matchup hypothesis tracker (record a theory, validate it after N matches)
- Sideboard planning system (per-matchup, usage tracking across sessions)
- Gauntlet builder (auto-select top meta decks to test against)
- Test recommendation engine (what to test next based on logged gaps)
- Testing insights (patterns from logged match history)

## Current file ownership (existing code — not moved yet)

None yet. This system is greenfield — no existing files map here.
The `db/saved_decks.py` module (in progress) will be the first file
under this system's ownership once the My Decks feature is complete.

## Planned features (from ROADMAP)
- Match logging (opponent arch, result, play/draw, notes)
- Card swap rationale tracker (why you changed cards)
- Matchup hypothesis tracker (record + validate theories)
- Sideboard planning system (per matchup, usage tracking)
- Gauntlet builder (auto top decks to test against)
- Test recommendation engine
- Testing insights from logged matches
