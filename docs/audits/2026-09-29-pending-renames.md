# Pending archetype renames -- audit 2026-09-29

What `python -m analysis.archetypes --apply` would change in `decks.archetype` (read-only audit, `scripts/audit_pending_renames.py`): **75 labels, 3,231 decks** (89 format/label rows).

- 56 rows look like the same deck (set cosine >= 0.9).
- 6 rows need a decision (below).
- 14 rows have no same-format target decks to compare (pure renames; listed last).

## Needs a decision

Per-deck check: each source deck vs the target's own decks. OUTLIER = every source deck is below the target's 5th percentile; MIXED = some are.

| Verdict | Format | Label -> target | Decks | Set cos | Source decks | Target p5 / median | Kind |
|---|---|---|---|---|---|---|---|
| **MIXED** | modern | Death & Taxes -> Death And Taxes | 6 | 0.603 | 0.71, 0.65, 0.33, 0.33, 0.27, 0.25 | 0.41 / 0.73 | alias |
| **MIXED** | modern | U Tron -> Blue Tron | 2 | 0.81 | 0.79, 0.68 | 0.77 / 0.77 | alias |
| **OUTLIER** | pauper | Esper Affinity -> Grixis Affinity | 1 | 0.454 | 0.45 | 0.5 / 0.94 | alias |
| **OUTLIER** | pauper | Mono-u Fae -> Mono U Fae | 1 | 0.8 | 0.8 | 0.87 / 0.98 | formatting |
| **OUTLIER** | pauper | Mono-w Heroic -> Mono W Heroic | 1 | 0.721 | 0.72 | 0.82 / 0.91 | formatting |
| **OUTLIER** | pauper | Monor Madness -> Mono Red Madness | 1 | 0.883 | 0.88 | 0.92 / 1.0 | alias |

## Checked, fits the target (set cosine < 0.90 but each deck within the target's range)

| Format | Label -> target | Decks | Set cos | Kind |
|---|---|---|---|---|
| modern | 4C Control -> Four-Color Control | 365 | 0.841 | alias |
| pauper | Devotion to Black -> Devotion To Black | 1 | 0.726 | formatting |
| pauper | Dimir Affinity -> Grixis Affinity | 1 | 0.582 | alias |
| pauper | Golgari Dredge -> Jund Dredge | 8 | 0.882 | alias |
| pauper | Mono-green Stompy -> Mono Green Aggro | 1 | 0.283 | alias |
| pauper | Monou Faeries -> Mono Blue Faeries | 1 | 0.831 | alias |
| pauper | Reanimator -> Dimir Reanimator | 4 | 0.778 | alias |
| pauper | UR Skred -> Izzet Skred | 3 | 0.845 | formatting |
| pauper | Ub Affinity -> Grixis Affinity | 1 | 0.567 | alias |
| pauper | Ub Terror -> Dimir Terror | 1 | 0.876 | formatting |
| pauper | Ur Skred -> Izzet Skred | 2 | 0.887 | formatting |
| pauper | Urza Tron -> Urzatron | 1 | 0.717 | alias |
| pauper | WW Heroics -> Ww Heroics | 1 | 0.67 | formatting |

## Formatting-only renames (no alias involved)

Title-casing can make a name worse or leave it split from its real group (e.g. 'Mono U Fae' never joins 'Mono Blue Faeries').

| Format | Label -> result | Decks |
|---|---|---|
| pauper | UR Terror -> Izzet Terror | 6 |
| pauper | UR Skred -> Izzet Skred | 3 |
| pauper | Ur Terror -> Izzet Terror | 3 |
| pauper | Ubr Madness -> Grixis Madness | 2 |
| pauper | Ur Skred -> Izzet Skred | 2 |
| pauper | 4c Gates -> 4C Gates | 1 |
| pauper | 6-land Spy -> 6-Land Spy | 1 |
| pauper | Bg Gardens -> Golgari Gardens | 1 |
| pauper | Devotion to Black -> Devotion To Black | 1 |
| pauper | Mono-u Fae -> Mono U Fae | 1 |
| pauper | Mono-w Heroic -> Mono W Heroic | 1 |
| pauper | Permiso No. Correte. (rdw) -> Permiso No. Correte. (Rdw) | 1 |
| pauper | Rg Germination -> Gruul Germination | 1 |
| pauper | SimicDelver -> Simicdelver | 1 |
| pauper | Ub Haddinity -> Dimir Haddinity | 1 |
| pauper | Ub Terror -> Dimir Terror | 1 |
| pauper | WW Heroics -> Ww Heroics | 1 |

## No same-format target decks (cannot be compared)

| Format | Label -> target | Decks | Kind |
|---|---|---|---|
| pioneer | Weenie White -> White Weenie | 304 | alias |
| legacy | Weenie White -> White Weenie | 25 | alias |
| standard | Weenie White -> White Weenie | 25 | alias |
| pioneer | 4C Control -> Four-Color Control | 10 | alias |
| legacy | Urza Tron -> Urzatron | 6 | alias |
| modern | Weenie White -> White Weenie | 6 | alias |
| pauper | Ubr Madness -> Grixis Madness | 2 | formatting |
| modern | Bogle -> Bogles | 1 | alias |
| pauper | 4c Gates -> 4C Gates | 1 | formatting |
| pauper | 6-land Spy -> 6-Land Spy | 1 | formatting |
| pauper | Permiso No. Correte. (rdw) -> Permiso No. Correte. (Rdw) | 1 | formatting |
| pauper | Rg Germination -> Gruul Germination | 1 | formatting |
| pauper | SimicDelver -> Simicdelver | 1 | formatting |
| pauper | Ub Haddinity -> Dimir Haddinity | 1 | formatting |

## Reviewer notes (2026-09-29, by hand)

- **modern Death & Taxes -> Death And Taxes (MIXED)** -- alias is RIGHT. 4 of the 6 decks are Death and Taxes from
  different eras (Vial / Thalia / Stoneforge / Archon, 2023-2025). The 2 low scorers (2025 RCQ, 2025 MTGO League)
  are Orzhov Blink (Fatal Push, Thoughtseize, Overlord of the Balemurk, Ketramose, Ephemerate) MISLABELLED at the
  source as "Death & Taxes" -- a scraper-label problem, not an alias problem.
- **pauper Esper Affinity -> Grixis Affinity (OUTLIER, 1 deck)** -- the one alias that merges a different color
  pair. Recommend: drop `esper affinity` from ALIASES (let it stay its own label).
- **Mono-u Fae / Mono-w Heroic** -- formatting only, but the result ('Mono U Fae', 'Mono W Heroic') never joins
  'Mono Blue Faeries' / the heroic group: add aliases to the proper names instead of relying on title-casing.
- **Monor Madness, U Tron** -- same deck (scores near the target's range, 1-2 decks); keep.
- The 9/28 concerns (Rakdos/Jund Affinity -> Grixis Affinity, UW Tempo -> Azorius Control, Gruul Elves, an accented
  player name) are **no longer in the DB** as pending renames: the current `--apply` dry run lists 75 labels, and
  none of them.
