# How to Use MTG Meta Analyzer

A quick guide to every feature in the app.

---

## Getting Started

1. **First launch**: The setup wizard downloads card data and scrapes initial events
2. **Daily updates**: Background tasks run at 6 AM and 5 PM automatically
3. **Manual refresh**: Click the Refresh button on Dashboard anytime

---

## DASHBOARD

Your home screen — shows the current meta at a glance.

| Panel | What it shows |
|---|---|
| **Recent Top Finishes** | Latest tournament results (placement 1-4). Double-click an archetype to see the full decklist. Click the Event column to see all decks from that tournament. |
| **Win Rate** | Archetypes ranked by win %. Columns: Win% (★ = real match data), Change, Rating (Glicko-2), Prep Priority, Status (Pillar/Trap/Underplayed/Fringe), Tier, Role |
| **Popular** | Archetypes ranked by appearances with % change vs prior period |

**Buttons:**
- **Meta Shift** — Compare current meta to the prior period. Shows what's rising, falling, new, and gone.
- **Best Deck** — Recommends the best deck for the current meta based on matchup data and trends.
- **Refresh** — Reload all panels with current filter settings.

**Filters:** Format, Timeframe (1 week to All Time), Top N, Dedup toggles.

**Charts:** Toggle between Popularity Over Time and Win Rate Over Time. Check/uncheck archetypes to show/hide lines. Toggle Daily/Weekly granularity and Show Events (set releases, bans, rotations).

---

## META tab

### Charts
Interactive charts with format/timeframe/archetype controls.
- **Meta Share** — Line chart of meta share % per week
- **Archetype Trend** — Dual-axis: bars = appearances, lines = meta%/win%/top8%
- **Compare Trends** — Overlay multiple archetypes on one chart
- **Meta Positioning** — Scatter plot: X = meta share, Y = win rate (with card art bubbles)
- **Matchup Heatmap** — NxN grid of win rates

### Matchup Data
Win-rate matrix showing how every archetype performs against each other.
- **Real Match Data (DB)** — Uses actual match results from melee.gg (★ star indicator)
- **MTGDecks Live** — Scrapes win rates from MTGDecks.net
- **Gauntlet** — Builds a grid from top 12 meta decks
- **Export Decks** — Exports average decklists as .txt files for mtg-sim gauntlet testing
- **Equilibrium** — Nash equilibrium analysis showing optimal vs actual meta shares
- **Right-click any cell** to add team notes (persists across sessions)

### Predictions
Auto-generated meta predictions and accuracy tracking.

---

## DECKS tab

### Analyze
Paste any decklist (Arena, MTGO, Moxfield format) to analyze it.

**What you get:**
- **Blunder Detection** — Checks land count, mana curve, color consistency, interaction count, deck size, legality. Scores Major/Moderate/Minor issues.
- **Chapin Principles** — Rates your deck 0-10 on Threats, Answers, Consistency, Velocity, Mana, Clock.
- **Legality Check** — Verifies every card is legal in the selected format.
- **Auto-classify** — KNN identifies your archetype automatically.
- **Baseline Comparison** — Shows cards you run that most don't, cards you're missing, and quantity differences vs the average deck.
- **Deck Similarity** — How similar your list is to meta archetypes.

**Load Average Deck:** Pick any archetype from the dropdown → loads the statistical average decklist ready to analyze or export.

### My Decks
Save your decklists and sideboard plans.

- **Add/Edit/Delete** decks with name, format, archetype, notes
- **Sideboard Plans** — For each opponent matchup: play/draw IN/OUT cards, difficulty rating, notes
- **Export** — MTGO .txt, MTGA .txt, or decklist.org tournament sheet
- **Export Guide** — Print-friendly HTML with all your SB plans
- **Share JSON / Import JSON** — Share decks + plans with teammates

---

## SEARCH tab

Three sub-tabs:

### Card Browser
Full Scryfall-style card database. Search with query syntax:
```
t:creature c:red cmc<=3        # red creatures CMC 3 or less
o:"draw a card" f:standard     # standard-legal draw spells
r:mythic is:legendary          # mythic legendaries
k:flying pow>=4                # flyers with 4+ power
```
Card detail panel shows oracle text, legalities, meta usage, Similar Cards, and Functional Substitutes.

### Deck Search
Search tournament decklists by archetype, player, or format. Click any result to see the full list.

### Head-to-Head
Compare two archetypes side-by-side with win rates and matchup history.

---

## TOURNAMENT tab

### Event Optimizer
Plan for specific events (RCQ, RC, PTQ, Custom).

1. Select event type → auto-fills player count and rounds
2. Pick your deck (or load a saved one)
3. Enter the expected field (or click "Use Meta Distribution")
4. **Results:** Top-cut probability (binomial math), X-loss cutoff, field grade, per-matchup breakdown with G1/G2-G3 win rates, sideboard recommendations, encounter probability

### Match Log
Track your tournament results and personal win rates.

- **Log Match** — Record opponent, result, play/draw, game-by-game scores, notes
- **Stats Table** — Your WR per matchup vs Meta WR with delta (green = outperforming, red = underperforming)
- **SB Advice** — Identifies your weakest matchups and suggests sideboard adjustments based on guides and meta data
- **Trend Chart** — Your win rate over time

---

## RESOURCES tab

### Guides & Bookmarks
Sideboard guides synced from Skill Issue Magic sheet + your saved bookmarks.

### Ask Claude (requires API key)
Chat with Claude AI about the meta, card choices, and strategy. Injected with live meta context from your database.

### Set Analysis (requires API key)
Analyze new set spoilers for competitive impact. Fetch card lists from Mythic Spoiler, classify each card (Rate Outlier, Engine Piece, Enabler, SB Breaker, Upgrade Card), see impact per archetype.

---

## SETTINGS

- **Formats** — Choose which formats to scrape and maintain data for
- **Storage** — Database size, event counts. "Collect More Data" for manual backfill. "Scan Duplicates" to find cross-source duplicate events.
- **ML Models** — Download card embeddings, train Card2Vec and KNN classifiers
- **API Key** — Anthropic API key for Ask Claude and Set Analysis tabs

---

## Tips

- **Hover everything** — Most buttons and column headers have tooltips explaining what they do
- **Double-click archetypes** — Opens the detail dialog with average deck, recent lists, tech choices, card trends, and guides
- **Right-click heatmap cells** — Add team notes that persist across sessions
- **System tray** — The app stays in the tray when you close it. Right-click for status, "Run Now" to trigger a scrape, or Exit to fully quit
- **Keyboard shortcut**: `Ctrl+R` on Dashboard to refresh
