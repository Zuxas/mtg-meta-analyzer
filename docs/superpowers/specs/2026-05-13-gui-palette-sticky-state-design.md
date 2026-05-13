# GUI Quick Wins — Command Palette + Sticky State

**Status:** PROPOSED
**Created:** 2026-05-13
**Project:** mtg-meta-analyzer
**Estimated time:** 1 session (~6-8 hours)
**Arc:** Direction A of the GUI ergonomics brainstorm. Follow-up arc C (design language pass) queued after a week of palette-usage data.

---

## Goal

Cut cross-cutting GUI friction by adding (1) a global command palette for fast navigation and action triggering, and (2) sticky UI state so filters / format / timeframe / selections survive tab switches and app restarts.

This is the smallest scope that targets the two friction types most felt in daily flow (action cost + context cost) without competing with the May 29 RC prep timeline.

## Scope

**In scope:**

1. `gui/widgets/command_palette.py` — modal QDialog triggered by Ctrl+K, searches tabs / archetypes / saved decks / cards / actions with fuzzy matching, executes on Enter.
2. `gui/state.py` — `UIState` singleton wrapping a new `ui_state` key in `data/preferences.json`. Dotted-path get/set API with debounced disk save (250ms).
3. Hook into `gui/main_window.py` — register global `QShortcut(Ctrl+K)`, construct `UIState` singleton, pass to each tab at construction.
4. Per-tab hydration/persistence wiring for the state slices listed below. Each tab reads its slice on `showEvent` and writes on widget change.
5. Palette action `> Reset UI state` — clears the `ui_state` key.
6. Settings tab — add a button "Reset UI state" as fallback discovery path.

**Out of scope:**

- No tab visual redesign, no layout refactor (Direction C arc).
- No configurable hotkey (Ctrl+K hard-coded).
- No multi-step palette flows; "Set format → Standard" / "Set format → Modern" are separate entries.
- No Scryfall live fallback for cards; local `card_data` table only.
- No scroll-position persistence, no sort column/direction persistence, no window/splitter geometry persistence.
- No keyboard shortcut system beyond Ctrl+K.

## Architecture

Two new modules, both small. Decoupled — palette can ship without sticky state and vice versa, but they're designed to ship together for the user-facing punch.

```
                    ┌────────────────────────┐
                    │   gui/main_window.py   │
                    │  ┌──────────────────┐  │
   Ctrl+K  ─────────┼──┤ QShortcut → open │  │
                    │  └──────────────────┘  │
                    │  ┌──────────────────┐  │
                    │  │  UIState init    │──┼──── reads/writes ──→ data/preferences.json
                    │  └──────────────────┘  │
                    │           │            │
                    └───────────┼────────────┘
                                │
                    ┌───────────┴────────────┐
                    ▼                        ▼
       gui/widgets/command_palette.py    each gui/tabs/*.py
       (reads command registry,           (gets UIState in __init__,
        executes selected entry)           reads slice in showEvent,
                                           writes slice on change)
```

Both modules reuse the existing Inter font + dark theme from `gui/theme.py`. No new fonts, no new color tokens.

---

## Section 1 — Command Palette

### Behavior

- **Triggers:** `Ctrl+K` global; modal blocks the main window until dismissed.
- **Keys:** Esc closes · ↑/↓ navigates · Enter executes · Tab completes prefix · clicking outside closes.
- **Size:** ~600×400, frameless, centered on the main window.
- **Search input** auto-focused on open. Results below grouped by category with subtle dividers.
- **Empty input state:** shows **Recent** (last 5 selections from `ui_state.palette_recents`) then **Suggested** (3-4 high-value defaults: Jump to Dashboard, Open Settings, etc.).

### Result rows

Each row:
- Category tag chip (TAB / ARCH / DECK / CARD / ACT) — color-coded subtly.
- Primary line: name with bolded match characters.
- Secondary line: context (e.g., "Standard, 19.2% meta" for an archetype, "saved 2026-05-12" for a deck).

### Searchable registry

| Category | Source | Count | Refreshed |
|---|---|---|---|
| TAB | Walk `QTabWidget` tree at startup | ~28 (7 top + 21 sub) | App start + on tab structure change |
| ARCH | `analysis/archetypes.py` enumerated names | ~100-200 | App start + on F5 |
| DECK | `saved_decks` table | <50 typical | On save/delete |
| CARD | `card_data` table (already local, ~32k) | 32k | Weekly Scryfall refresh |
| ACT | Static registry in `command_palette.py` | ~15 | Code-time |

### Action registry (v1)

Stable command IDs (used by `palette_recents` so they survive renames / tab reorgs):

- `act:refresh-current-tab` — Refresh current tab (same as F5)
- `act:sync-guides` — Sync Guides from Skill Issue Magic sheet
- `act:scrape-run-now` — Run Now → Scrapers menu
- `act:format-standard` / `act:format-modern` / `act:format-pioneer` / `act:format-legacy` / `act:format-pauper` — Toggle format (each format is its own entry — no multi-step palette flows)
- `act:open-settings`
- `act:open-set-analysis`
- `act:open-ask-claude`
- `act:print-sb-guide` — **context-aware**: only registered when My Decks tab is active and a deck is selected
- `act:export-deck-mtgo` / `act:export-deck-mtga` / `act:export-deck-decklistorg` — context-aware: My Decks + deck selected
- `act:reset-ui-state` — clears `ui_state` key

### Fuzzy matching

- `thefuzz` (already in requirements per CI fix). `process.extract` with `WRatio` scorer, top 8 across categories.
- All sources indexed in-memory at startup (~200 strings + 32k card names = trivial).
- No DB re-query per keystroke.
- **Card category gating:** because 32k card names would flood results, cards only surface when (a) input is prefixed `c:` OR (b) input is ≥2 chars AND no non-card results match. This prevents incidental card spam on short queries.

### Quick-jump prefixes (VS Code style)

- `>` actions only
- `#` tabs only
- `@` archetypes only
- `:` decks only
- `c:` cards only
- No prefix = mixed top-N

### Context-awareness (judgment call locked)

Some actions only make sense in context (Print SB Guide requires a selected deck on My Decks). These actions are **registered/unregistered as context changes**, so they never appear in the palette when they wouldn't work. Avoids "this doesn't work right now" surprises. The trade-off: less predictable command set, but predictable success rate.

### Stability for future tab reorganization (Arc C compatibility)

- Palette walks the `QTabWidget` tree dynamically — no hard-coded tab list.
- Recents store stable command IDs (e.g., `tab:my-decks`), not display strings.
- Reorganize tabs later → palette adapts on its own → recents survive.

---

## Section 2 — Sticky UI State

### Storage

Extend `data/preferences.json` with one new top-level key. Existing keys (`formats`, `api_key`, etc.) untouched.

```json
{
  "formats": [...],
  "api_key": "...",
  "ui_state": {
    "global": {
      "format": "Standard",
      "timeframe": "4w",
      "last_active_tab_path": "Decks/My Decks"
    },
    "tabs": {
      "dashboard":    { "selected_archetype": "Izzet Prowess",
                        "chart_archetypes": ["Izzet Prowess", "Selesnya Landfall"] },
      "my_decks":     { "selected_deck_id": 17 },
      "charts":       { "archetypes": [...], "chart_type": "popularity" },
      "matchup_data": { "top_n": 12, "source_filter": "all" },
      "scout":        { "days": 14, "target_archetypes": ["Izzet Prowess"] }
    },
    "palette_recents": ["arch:izzet-prowess", "tab:dashboard", "act:refresh-current-tab"]
  }
}
```

### API

`gui/state.py` exposes a singleton:

- `UIState.get(path: str, default=None) -> Any` — dotted path access; always returns `default` if missing.
- `UIState.set(path: str, value: Any) -> None` — sets value, debounced 250ms save to disk.
- `UIState.reset() -> None` — clears the `ui_state` key entirely.
- `UIState.load() -> None` — reload from disk (used after corrupt-JSON recovery and tests).

### Hydration

Each tab's `showEvent(QShowEvent)` hook:

1. Reads its slice via `UIState.get("tabs.<tab_id>.*", default)`.
2. Wraps widget value-application in `widget.blockSignals(True)` / `False` so hydration does not re-trigger `*Changed` signals (which would cause both a save loop AND fire user-facing change handlers as if the user had clicked).
3. Calls `self.refresh()` (or equivalent) only after hydration completes, so the rendered state reflects the restored selections.

Global state (format, timeframe, last_active_tab_path) hydrates once on `MainWindow.__init__` before any tab `showEvent` fires.

### Persistence

- Filter / selector widgets connect their `*Changed` signals to a small `_persist_state()` method on each tab.
- `_persist_state()` calls `UIState.set("tabs.<tab_id>.<field>", value)` — debounced disk write happens inside `UIState`.
- 250ms debounce prevents disk thrash when dragging sliders or rapidly switching dropdowns.

### Persisted slices (v1 scope)

| Slice | Reason |
|---|---|
| `global.format` | Tab switches losing format selection — root cause of context-cost friction |
| `global.timeframe` | Same |
| `global.last_active_tab_path` | App reopens where you closed it |
| `tabs.dashboard.selected_archetype` | "I had it set, now it's gone" pain |
| `tabs.dashboard.chart_archetypes` | Same |
| `tabs.my_decks.selected_deck_id` | Tokyo Prowess (id=17) pre-selected on launch |
| `tabs.charts.archetypes` + `chart_type` | Same context-loss pattern |
| `tabs.matchup_data.top_n` + `source_filter` | Same |
| `tabs.scout.days` + `target_archetypes` | Same |

### NOT persisted (deferred)

- Scroll positions on tables.
- Sort column / direction. (Often valuable — deferred until usage data shows demand.)
- Window geometry / splitter positions.
- Modal dialog state.

### Edge cases

- **Stale archetype** (selected name no longer in DB): silently fall back to "no selection", log to stderr.
- **Stale deck ID** (saved_decks row deleted): same fallback.
- **Stale palette recents** (recent points to a command ID that's no longer in the registry — e.g., archetype was renamed, saved deck was deleted): silently filter out on render and prune from the persisted list on next save. No user-visible error.
- **Corrupt `ui_state` JSON**: ignore the whole `ui_state` key, fall back to defaults, log warning to stderr. The rest of `preferences.json` is preserved.
- **Schema migrations** (new fields added later): never breaking — `UIState.get(path, default)` always provides a default for missing fields.

### Reset path

Two surfaces:
1. Palette action `act:reset-ui-state` — fast for power users who already know the palette.
2. Button "Reset UI state" in Settings tab — fallback discovery path for users who don't.

---

## Testing approach

Project does not currently have a Qt test suite (no `pytest-qt` in requirements, no `test_gui_*.py` files). Test scope:

**Unit (pure-Python, no Qt):**
- `gui/state.py` `UIState` get/set/reset with mocked filesystem. Verify debounce semantics with `unittest.mock` clock control. Verify graceful corrupt-JSON recovery.
- Palette fuzzy-matching helpers (registry indexing, prefix parsing, category gating) without instantiating QDialog.

**Manual smoke (documented checklist in spec, not automated):**
- Open palette with Ctrl+K, type a few chars, navigate with ↑/↓, execute with Enter.
- Switch tabs, verify format selector keeps value.
- Restart app, verify last active tab is restored.
- Delete `saved_decks.id=17` from DB, restart, verify graceful "no deck selected" state on My Decks.
- Corrupt `ui_state` JSON manually, restart, verify app launches with default state.

Pre-shipping a Qt test harness is out of scope; manual smoke is the gate for v1.

## Imperfections (known limits going in)

1. **Static action registry.** New tabs / features won't be in the palette until their actions are registered in code. Mitigation: enumerate tabs dynamically; only the action list is hand-curated. Adding an action is one line.
2. **No fuzzy match against secondary fields.** "Izzet Prowess" matches by name, not by archetype color identity (`UR`) or pilot ("Tokyo"). Mitigation: add a `keywords` field per registry entry later if needed.
3. **No multi-deck selection in palette.** "Open all my Izzet decks" isn't a thing — one selection per Enter. Mitigation: not a real pain yet; defer.
4. **Card category may feel walled-off behind `c:`.** Power users learn the prefix; new users may not discover it. Mitigation: brief hint text in empty-state ("type c: to search 32k cards"). Track usage data; revisit gate threshold if cards are under-used.
5. **Settings tab gains a button that 99% of users will never need.** Acceptable cost for a discoverable reset path.

## Open questions

- None blocking for v1. Two judgment calls already locked: card-prefix gating, context-aware action registration.

## Future work (Arc C lead-in)

- Once palette has 1+ week of usage data (`palette_recents` + a usage-count column), use it to inform the Arc C design system: which commands you actually reach for tells us which actions deserve top-level prominence vs. which can stay palette-only.
- Tab reorganization (Arc C territory): when it lands, palette's dynamic tree walk + stable command IDs mean zero re-wiring needed.
- Sort / scroll persistence: revisit after a week of using the v1 sticky-state slices to see whether the omission hurts.

## Changelog

- 2026-05-13: PROPOSED. Brainstormed in session 2026-05-13-AM; direction A locked, C queued as follow-up arc.
