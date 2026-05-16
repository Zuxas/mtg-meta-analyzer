# Find-the-Line Puzzle Tool — Design

**Date:** 2026-05-16
**Author:** brainstorming session with the user
**Status:** approved by user, ready for implementation plan
**Driver:** sequencing reps for Tokyo Izzet Prowess + Standard meta before RC DC (5/29-5/31, 13 days out)

## Problem

Reps are the limiting factor for sequencing skill on a combo-leaning deck like
Tokyo Prowess. Real MTGA queue time is slow; sparring partners aren't always
available; goldfish testing doesn't simulate opponent boards. There's no
existing tool in the project that lets the pilot say "here's a board state — find
the line" the way Möbius / Possibility Storm let users practice puzzle scenarios.

The pilot has already accumulated a corpus of real match replays
(`data/match_replays/*.json` — full per-turn gameStateMessage annotations,
captured by the 5/14 Watch Replay infrastructure). These contain enough state
to reconstruct any prior board position. They're the natural raw material for
puzzle scenarios.

## Goal

A puzzle-practice tool inside the meta-analyzer GUI that:

1. **Auto-extracts candidate puzzle scenes** from the user's own replay corpus
   based on per-category heuristics (lethal-on-board, low-life-survived,
   tempo-decisions).
2. **Lets the user author** the extracted candidates into finished puzzles
   (question, solution(s), difficulty, category).
3. **Renders each scene** in an MTGA-like visual layout (real card images,
   centered life circles, mirrored zones, fanned hand) so pattern recognition
   transfers to actual play.
4. **Verifies the user's answer** via one of three modes per puzzle: self-grade
   after reveal (default), tagged-keyword auto-check, or LLM-graded via Claude
   API (with graceful fallback to self-grade when no API key is configured).
5. **Tracks practice history** (attempts, verdicts, time-to-solve) so the user
   can see WR per category and identify recurring weak spots.
6. **Lives as a top-level `PUZZLES` tab** alongside the existing 7 tabs.

## Non-goals (out of scope)

- A puzzle engine that simulates the rules (no resolving spells, no validating
  legality of the user's proposed line). The user reads their own answer; the
  grader checks intent, not legality.
- Auto-generating puzzles via LLM (e.g. "generate a novel position for Tokyo
  Prowess"). Manual authoring on top of scanner candidates only.
- Mobile / web / external distribution. Lives inside the Qt GUI.
- Sharing puzzles via real-time multi-user sync. JSON export/import only for
  v1; shared DB deferred to Phase 4 post-RC.

## Decisions (locked through brainstorm Q&A)

| Decision | Choice |
|---|---|
| Source | Auto-seeded from `data/match_replays/*.json` + manual editing of each candidate |
| Categories | Three: 🎯 Find lethal, 🛡 Stabilize, ⚡ Tempo / Race-correctly |
| Render style | MTGA-like: Scryfall card images, corner avatars, centered life circles, mirrored zones, fanned hand (per `puzzle-mtga-v5.html` mockup) |
| Verification | All three modes configurable per puzzle: self-grade (default) / tagged-keyword / LLM-graded; LLM gracefully falls back to self-grade when no API key |
| UI placement | New top-level `PUZZLES` tab (8th tab, before Settings) |
| Authoring entry points | Two, same dialog: (1) PUZZLES → Inbox lists scanner candidates; (2) right-click any turn in `gui/widgets/deck_match_history.py` → "Create puzzle from this turn" |
| Sharing | Personal DB storage + JSON export/import per puzzle (v1) + shared-DB sync (Phase 4, deferred post-RC) |

## Architecture

Six components with one clear responsibility each. Each can be tested in
isolation.

### `analysis/puzzles/scanner.py`

Walks `data/match_replays/*.json`. For each replay, walks turns. Per category,
applies heuristic to identify candidate turns. Returns `list[Candidate]`
(no DB write). Pure function from disk JSON to candidate dicts.

Heuristics:

- **🎯 Find lethal**: turn N where (a) you cast ≥ 3 noncreature spells AND
  opp life dropped from ≥ 8 → 0 within turn N (the "burned them out" moment),
  OR (b) total prowess-attack potential on board ≥ 4 but you skipped combat.
- **🛡 Stabilize**: turn N where your life ≤ 5 AND match continued past N AND
  you eventually won the match.
- **⚡ Tempo / Race**: turn N where you cast an instant-speed removal at
  sorcery speed (no mana held up after cast) AND opp's next turn had a
  trigger that would have benefited from instant-speed response. OR turn N
  where attacking would have shortened opp's clock by ≥ 1 turn vs the line
  actually taken.

Each Candidate dict has: `arena_match_id`, `game_num`, `turn_num`, `category`,
`heuristic_score` (for ranking in Inbox), `evidence` (text snippet describing
why this turn was flagged).

**heuristic_score formula:** per-category, normalized to [0.0, 1.0]:

- Find lethal: `0.6 * (spells_cast / 5) + 0.4 * (1 - opp_final_life / starting_life)`
- Stabilize: `0.5 * (1 - your_life_at_turn / 20) + 0.5 * (did_win_match ? 1.0 : 0.5)`
- Tempo: `0.5 * (turns_saved_vs_actual / 3) + 0.5 * (mana_efficiency_delta)`

Formulas are first-pass guesses. Tuning happens in Phase 2 after observing
which scored-high candidates the user actually promotes vs dismisses. Tuning
log lives in `analysis/puzzles/SCANNER_TUNING.md`.

### `db/puzzles.py`

Schema (3 tables, all CREATE IF NOT EXISTS in `_ensure_tables()`):

```sql
CREATE TABLE puzzles (
    id              INTEGER PRIMARY KEY,
    deck_id         INTEGER REFERENCES saved_decks(id) ON DELETE CASCADE,
    arena_match_id  TEXT,             -- source replay (nullable for hand-authored)
    game_num        INTEGER,
    turn_num        INTEGER,
    category        TEXT NOT NULL,    -- 'find_lethal' | 'stabilize' | 'tempo'
    difficulty      INTEGER NOT NULL, -- 1..5 stars
    question        TEXT NOT NULL,    -- "Find lethal", "Survive opp's T8", etc.
    solution_text   TEXT NOT NULL,    -- author's prose solution (revealed)
    solution_keywords_json TEXT,      -- ["bounce_worldwagon","burn_elf"] for keyword grader
    grading_mode    TEXT NOT NULL,    -- 'self' | 'keyword' | 'llm'
    author          TEXT,             -- 'auto-seeded' | local user handle | imported handle
    notes           TEXT,             -- explanation, hints, alternate lines
    scene_json      TEXT NOT NULL,    -- serialized Scene snapshot at author time;
                                       -- protects against source replay being deleted later
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE puzzle_attempts (
    id              INTEGER PRIMARY KEY,
    puzzle_id       INTEGER NOT NULL REFERENCES puzzles(id) ON DELETE CASCADE,
    attempted_at    TEXT NOT NULL,
    user_answer     TEXT NOT NULL,    -- free-text the user typed
    verdict         TEXT NOT NULL,    -- 'correct' | 'incorrect' | 'partial'
    grader_used     TEXT NOT NULL,    -- 'self' | 'keyword' | 'llm' (may differ from puzzle.grading_mode if fallback)
    time_spent_ms   INTEGER
);

CREATE TABLE puzzle_inbox (
    id              INTEGER PRIMARY KEY,
    arena_match_id  TEXT NOT NULL,
    game_num        INTEGER,
    turn_num        INTEGER NOT NULL,
    category        TEXT NOT NULL,
    heuristic_score REAL NOT NULL,    -- ranking
    evidence        TEXT,
    discovered_at   TEXT NOT NULL,
    dismissed_at    TEXT,             -- nullable; set when user dismisses without promoting
    promoted_puzzle_id INTEGER REFERENCES puzzles(id) ON DELETE SET NULL
);

CREATE INDEX idx_puzzles_deck ON puzzles(deck_id);
CREATE INDEX idx_puzzles_category ON puzzles(category);
CREATE INDEX idx_attempts_puzzle ON puzzle_attempts(puzzle_id);
CREATE INDEX idx_inbox_undismissed ON puzzle_inbox(dismissed_at, heuristic_score DESC);
```

API surface (mirrors existing `db/saved_decks.py` style):

- `get_puzzles(category=None, deck_id=None, unsolved_only=False) -> list[dict]`
- `get_puzzle(puzzle_id) -> dict | None`
- `save_puzzle(...) -> int` (insert + return id)
- `update_puzzle(puzzle_id, **fields)`
- `delete_puzzle(puzzle_id)`
- `record_attempt(puzzle_id, user_answer, verdict, grader_used, time_spent_ms)`
- `get_attempts(puzzle_id) -> list[dict]`
- `get_session_stats(since=None) -> dict` (returns `{n_solved, n_missed, wr_overall, wr_by_category}`)
- `save_inbox_candidates(candidates: list[Candidate])` — batched upsert
- `get_inbox(category=None, top_n=50) -> list[dict]` — undismissed, ranked
- `dismiss_inbox(inbox_id)`
- `promote_inbox(inbox_id, puzzle_id)` — links the inbox row to the new puzzle

### `analysis/puzzles/scene_builder.py`

Given `(arena_match_id, game_num, turn_num)`, reconstructs the full board state
from the replay transcript. Returns a `Scene` dataclass:

```python
@dataclass
class Scene:
    arena_match_id: str
    game_num: int
    turn_num: int
    play_or_draw: Literal["play", "draw"]

    you: PlayerState
    opp: PlayerState

    notes: str  # any contextual notes about how we got here (T5 opp cast X, etc.)

@dataclass
class PlayerState:
    name: str
    archetype: str
    life: int
    hand: list[CardInZone]            # face-up for you; just count for opp
    battlefield_lands: list[CardInZone]      # with tap state
    battlefield_creatures: list[CardInZone]  # with P/T, counters
    battlefield_other: list[CardInZone]      # enchantments, artifacts, planeswalkers
    graveyard_count: int
    library_count: int
    mana_available: dict[str, int]    # {"U": 2, "R": 1} after subtracting tapped lands

@dataclass
class CardInZone:
    name: str
    grpid: int | None
    scryfall_image_url: str | None    # None when card isn't in Scryfall (uses placeholder)
    tapped: bool = False
    power: int | None = None
    toughness: int | None = None
    counters: dict[str, int] = field(default_factory=dict)  # {"+1/+1": 2}
    is_face_down: bool = False
```

Reuses `analysis.replay_transcript.build_transcript()` to load the cached
replay JSON; walks turns up to the target turn building zone state.

### `analysis/puzzles/grader.py`

Strategy pattern. One factory + three concrete graders:

```python
class Grader(Protocol):
    def grade(self, user_answer: str, puzzle: dict) -> GraderVerdict: ...

@dataclass
class GraderVerdict:
    verdict: Literal["correct", "incorrect", "partial", "user_marked"]
    explanation: str            # what the grader thinks (for user feedback)
    grader_used: str            # 'self' | 'keyword' | 'llm' (may differ from puzzle.grading_mode)

def make_grader(puzzle: dict) -> Grader:
    """Returns the right grader, with LLM-fallback baked in."""
    mode = puzzle["grading_mode"]
    if mode == "llm" and not _has_api_key():
        return SelfGradeGrader()  # graceful fallback
    return {"self": SelfGradeGrader, "keyword": KeywordGrader, "llm": LLMGrader}[mode]()

class SelfGradeGrader:
    """User reveals + clicks Got it / Missed it. We just record their click."""

class KeywordGrader:
    """Lowercase + tokenize the user answer; check that each tagged keyword
    appears as a substring (with simple stemming: 'bouncing'==''bounce')."""

class LLMGrader:
    """Call Claude API with the puzzle's solution_text + user_answer,
    ask for 'correct' / 'partial' / 'incorrect' + explanation. ~$0.001-0.005
    per grade per Claude Haiku."""
```

### `gui/tabs/puzzles.py`

The new top-level tab. Internal QTabWidget with three sub-modes:

- **Solve** (default) — picks the oldest-unsolved puzzle from the filtered set
  (filter by category, deck, difficulty), renders via `PuzzleSceneWidget`,
  shows the question + answer textarea + Submit button. After Submit:
  invokes the grader, records the attempt, shows the verdict + author's
  solution + Got-it / Missed-it buttons (Got-it only when grader said
  correct; both buttons available on self-grade mode).
- **Inbox** — table view of scanner candidates ranked by heuristic_score.
  Columns: date, match, turn, category, score, evidence. Right-click row →
  "Author from this candidate" (opens Author dialog) or "Dismiss" (sets
  dismissed_at).
- **Author** — editor for one puzzle (new or existing). Renders the scene at
  the top (read-only preview from `PuzzleSceneWidget`), form below for
  question / solution_text / keywords / grading_mode / difficulty / category /
  notes. Save button writes via `db/puzzles.save_puzzle()`.

### `gui/widgets/puzzle_scene.py`

The MTGA-style render widget. Reusable: same widget renders in Solve mode and
in Author preview. Input: a `Scene` instance. Layout per the v5 mockup.

Card images pull from a local Scryfall cache at `data/card_images/<grpid>.jpg`
(file-per-card). Cache populator runs lazily — on first scene render, the
widget kicks off a `DataLoadWorker` that fetches missing images via
Scryfall's `/cards/named?exact=<name>&format=image&version=small` endpoint
(throttled to 10 req/sec per Scryfall's stated rate limit) and writes to the
cache. Subsequent renders read from disk. Cards not in Scryfall (e.g. very
new sets before bulk indexing) fall back to a text-placeholder rendering
(name + type + cost).

### Match-History right-click integration

`gui/widgets/deck_match_history.py` already has a recent-matches QTableWidget
with row click behavior. Add a context menu item:

```python
menu = QMenu(self)
view_action = menu.addAction("View transcript")
puzzle_action = menu.addAction("📥 Create puzzle from this turn")
puzzle_action.triggered.connect(lambda: self._on_create_puzzle(arena_match_id, game_num, turn_num))
```

The handler opens the Author dialog (from `gui/tabs/puzzles.py`) pre-loaded
with the (arena_match_id, game_num, turn_num) so the scene reconstructs but
question / solution / etc. are blank.

## Phasing

Each phase ships something the user can actually use before the next phase
starts. RC DC is 13 days out — a usable v0 by 5/18 means 11 days of practice
on the tool itself.

### Phase 1 — Solo solve loop (4-5h, ship target 5/18 Monday)

- `db/puzzles.py` schema (all 3 tables — `_ensure_tables()` creates them all
  in Phase 1 so Phase 2 doesn't need a migration; only `puzzles` +
  `puzzle_attempts` API surface is wired in Phase 1)
- `analysis/puzzles/scene_builder.py`
- `gui/widgets/puzzle_scene.py` (the MTGA-style widget)
- `gui/tabs/puzzles.py` with Solve mode only
- Self-grade verification only
- Author by hand-editing 2-3 puzzles via a CLI seeder script
  (`scripts/seed_puzzles.py`)

Ships: user can solve hand-authored puzzles end-to-end in the GUI.

### Phase 2 — Scanner + Inbox + Author dialog (4-5h, ship target 5/20 Wednesday)

- `puzzle_inbox` table + DB API additions
- `analysis/puzzles/scanner.py` with all 3 category heuristics
- Inbox sub-mode in PUZZLES tab
- Author dialog (form fields, scene preview, save)
- Right-click integration in Match History sub-tab

Ships: scanner extracts candidates from real replays → Inbox → user promotes
to puzzle → solve.

### Phase 3 — Keyword + LLM graders + score tracking (3-4h, ship target 5/22 Friday)

- `analysis/puzzles/grader.py` with all three implementations + factory
- LLM-no-API-key graceful fallback to SelfGrade
- Per-puzzle grading_mode setting in Author dialog
- Score tracking display in Solve mode (session stats: n_solved / n_missed /
  WR by category)

Ships: full verification flow + practice tracking.

### Phase 4 — JSON export/import + shared DB (2-3h, deferred post-RC after 5/31)

- JSON export per puzzle (single-puzzle and bulk)
- JSON import + dedup detection
- Multi-user shared DB sync (design TBD — likely a Google Sheet or
  SQLite-over-Dropbox model, evaluated after Phase 3 ships)

Ships: Team Resolve can share puzzles between members.

## Failure modes + mitigations

| Failure | Mitigation |
|---|---|
| Scanner produces too many candidates | Dedup per (match, turn). Rank by heuristic_score. Inbox UI shows top-50 per category by default with a "show all" toggle. |
| Replay transcript missing data (older matches) | Scene builder returns partial Scene with explicit `data_missing` flags. Author dialog warns before promoting an incomplete scene. |
| Scryfall image cache miss (very new cards) | Scene widget falls back to text-placeholder rendering (matches v5 mockup's Worldwagon / Dryadine placeholders). Cache backfills happen lazily on next render attempt. |
| LLM grader marks an equivalent answer "incorrect" | Show the LLM's explanation when verdict is incorrect / partial. Provide a "Override → I had it" button that overwrites the verdict in `puzzle_attempts`. Tracks LLM grader accuracy over time. |
| User dismisses every Inbox candidate | After 20 dismissals on the same category, surface a "Tighten heuristic?" hint that links to `analysis/puzzles/scanner.py` documentation. Scanner heuristics may need real-world tuning per user. |
| API key set but rate-limited / down | LLMGrader catches HTTP errors, logs to `logs/qt_msgs_*.log`, falls back to SelfGrade for the attempt with a banner ("LLM grader unavailable — please self-grade"). |
| User authors a puzzle, then deletes the source replay | `arena_match_id` becomes orphan but `puzzles.scene_json` (set at author time) already contains the serialized Scene. Solve mode prefers the snapshot when present, falls back to rebuilding from `arena_match_id` if the snapshot is missing (legacy puzzles). |

## Validation gates (per phase, mechanical)

- **Phase 1**: hand-author 3 puzzles via seeder script, open PUZZLES tab,
  solve each in <60s, verify attempts get recorded in `puzzle_attempts` table.
- **Phase 2**: run scanner on existing `data/match_replays/`, verify > 5
  candidates surface per category, promote at least 2 from each category to
  finished puzzles via Author dialog.
- **Phase 3**: same puzzle solved 3 ways (self / keyword / LLM), verify
  verdicts match author's intent ≥ 2/3 times per mode. Confirm LLM fallback
  fires when API key is unset (mock the no-key case).
- **Phase 4**: round-trip a puzzle through export → delete → import →
  verify identical.

## Dependencies

- Existing: `analysis.replay_transcript`, `db.database`, `db.saved_decks`,
  `gui.worker_threads.DataLoadWorker`, `gui.theme`, Qt6, requests (for
  Scryfall + Claude API).
- New: none required. Claude API access uses the existing
  `data/preferences.json::anthropic_api_key` slot already wired by
  `gui/tabs/ask_claude.py`.

## Related work

- 5/14 Watch Replay (`gui/widgets/replay_transcript_dialog.py`) — provides
  the replay JSON cache this tool reads from.
- 5/15 Match History sub-tab (`gui/widgets/deck_match_history.py`) — gets
  the right-click "Create puzzle" integration.
- Existing `analysis.sb_plan_diff` — same pattern of "compare what you did
  vs canonical"; puzzle tool extends the principle to live-position decisions.

## Out-of-scope (explicit non-goals)

- Rules-engine validation of user's proposed line
- LLM-generated novel puzzles (no real-board state)
- Mobile / web distribution
- Real-time multi-user puzzle sync (Phase 4 may use eventual-consistency Google Sheet)
