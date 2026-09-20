# Claude Code prompt — Chapin metrics + data-freshness guard

Context for the implementer: this repo already has `analysis/equilibrium.py`
(Nash / replicator dynamics / RPS cycles), `analysis/meta_scoring.py` (Pillar /
Trap / Underplayed / Fringe), `analysis/deck_ev.py` and
`analysis/field_optimizer.py` (field-weighted EV), and `analysis/wilson.py`
(confidence intervals). **Do not rebuild any of that.** Everything below is
either a refinement to an existing module or a genuinely absent piece.

Source for the strategy claims: Patrick Chapin, *Next Level Magic Forever*
(2026). Extracted rule set at `E:\vscode ai project\NLMF_Notes\nlmf_heuristics.json`; rule
ids are cited inline below.

Work the tasks in order. Task 1 is unrelated to Chapin and is the urgent one.

---

## Task 1 — per-format freshness guard (do this first)

**The bug.** `data/scrape_state.json` records one global `last_status`. On
2026-09-20 it read `ok` with `last_updated: 2026-08-29`, while the `matches`
table had held **zero Modern rows since 2026-06-26** and `events` had held no
Modern event since **2026-07-09**. Legacy and Pauper were current to 2026-09-13.
So a format-specific stall is completely invisible, on the format used for RC
prep. This is the same class of failure as the MTGTop8 Unicode bug.

Second defect in the same area: `matches.event_date` and `events.date` each
contain **both** `YYYY-MM-DD` and `dd/mm/yy` values (matches: 293,078 ISO vs
10,266 slash; events: 2,131 ISO vs 4,208 slash). Any `MAX(date)` or `date >= ?`
string comparison spanning both is wrong. `analysis/deck_ev.py::_default_field_shares`
already works around it with an inline `CASE`; nothing else does.

**Implement.**

1. `db/helpers.py`: add `normalize_event_date(value) -> str | None` returning
   ISO `YYYY-MM-DD`, handling both stored shapes and returning `None` on junk.
   Add a matching SQL fragment constant `SQL_NORM_DATE` (lift the `CASE`
   expression already in `deck_ev.py`) and refactor `deck_ev.py` to import it
   rather than keep its own copy.
2. New `analysis/data_health.py`:
   ```python
   def format_freshness(formats=None) -> dict:
       """{format: {last_match_date, last_event_date, matches_30d,
                    matches_prev_30d, days_stale, status}}"""
   ```
   `status` is `fresh` (< 10 days stale), `stale` (10–30), `dead` (> 30 days
   or zero rows in 60). Use the normalized date, not raw string compare.
3. Surface it. The dashboard already has a filter row and summary bar
   (`tests/test_dashboard_filter_row.py`, `test_dashboard_summary_bar.py`) —
   add a freshness chip next to the format selector: green / amber / red with
   the last-data date in the tooltip. **When the selected format is `dead`, every
   panel on that screen must show a banner saying the data is N days old.**
   A silently stale number is worse than no number.
4. Make `scrape_state.json` per-format: `{"formats": {"modern": {...}}}`, keep
   reading the old shape so existing installs don't break.
5. Tests in `tests/test_data_health.py`: mixed-date fixtures, a format with no
   recent rows, an empty table, and the old-shape scrape_state.

**Also worth a look while you are in there** (diagnosis, not spec): Modern
events are still arriving from `mtgtop8` but every Modern event since
2026-06-01 has `decks` rows and **zero** `matches` rows. The melee match
scraper, not the deck scraper, is what stopped. Check `scrapers/mtgmelee_scraper.py`
and the scheduled task before assuming the fix is in the app.

---

## Task 2 — conversion ratio and the cascade flag

**What.** Chapin's Information Cascades chapter (p.92, rule `IC-02`): a deck
played a lot wins a lot in absolute terms, which fuels more play. Ghost Dad was
winning mostly because it was *played*. The test is **conversion ratio** =
(share of top finishes) / (share of field). Near 1.00 means presence is
explained by popularity alone.

`meta_scoring.classify_status` only calls a deck a Trap when WR < 48%. A cascade
deck typically sits at ~50% — currently labelled Fringe or nothing. This adds
the missing axis.

**Critical implementation detail.** Derive field *and* top cut from the
**`matches` table only**. Do not join to `decks`:

- `decks` is top-cut biased (~12.4 rows per event; placement values bucket at
  4/8/16/32), so it cannot supply a field denominator.
- `decks` archetype labels come from a different scraper than the melee match
  rows, so the label sets do not reconcile. Mixing them produced Mono Red Aggro
  at 5.30% of the field and 0.03% of top 8s, and Domain Ramp at 3.06% / 0.00% —
  both artifacts, not findings.

Field = every distinct `(event_id, player)` appearing in `matches`. Top cut =
rank players within each event by swiss win count (ties broken by fewer losses)
and take the top N. Restrict to events with ≥ 16 distinct players.

**Implement.** New `analysis/conversion.py`:
```python
def conversion_by_archetype(format_name, since, until=None,
                            min_players=16, cut=8) -> dict:
    """{archetype: {field_share, top_share, conversion, match_wr,
                    matches, events, ci_low, ci_high}}"""
```
Reuse `analysis.wilson.wilson_bounds` for the interval on `match_wr` — do not
write a new one. Then extend `meta_scoring.classify_status` to take an optional
`conversion` argument and return a new `"Cascade"` status (suggest `#e67e22`)
when `meta_share >= 0.03 and conversion <= 1.02 and 0.48 <= win_rate <= 0.52`.
Existing four statuses and the current call signature must keep working
unchanged when `conversion` is not supplied.

**Reference output** (Modern, 2025-10-01..2026-06-30, 106 qualifying events,
14,648 field entries) — use as the fixture target:

| archetype | field% | top8% | conv | matchWR | n |
|---|---:|---:|---:|---:|---:|
| Boros Energy | 9.63 | 12.50 | 1.30 | 53.5 | 8074 |
| Jeskai Blink | 8.27 | 5.90 | 0.71 | 50.5 | 6746 |
| Izzet Prowess | 8.04 | 7.90 | 0.98 | 49.3 | 6125 |
| Izzet Affinity | 7.00 | 9.20 | 1.31 | 52.6 | 5631 |
| Mono Red Aggro | 5.30 | 7.19 | 1.36 | 52.3 | 3511 |
| Goryo's Vengeance | 5.09 | 3.42 | 0.67 | 49.0 | 3999 |
| Amulet Titan | 4.02 | 2.36 | 0.59 | 51.6 | 3871 |
| Domain Ramp | 3.06 | 4.48 | 1.47 | 49.7 | 2110 |

Flagged as cascades: Jeskai Blink, Izzet Prowess, Goryo's Vengeance, Amulet Titan.

A working reference implementation is in `scripts/data_health_report.py` —
port it, don't reinvent it.

**Honest limits to put in the docstring:** top cut is approximated from swiss
win count, with no tiebreakers, drops or byes, and a flat top-8 regardless of
event size. It is a signal, not a standing.

---

## Task 3 — match math in `deck_ev.py` (`MG-12`, p.90)

**The modelling gap.** `compute_deck_ev` takes a match win rate and adds a flat
sideboard bump (`Easy +5pp / Medium 0 / Hard −5pp`) straight to it. But a
sideboard plan acts on *post-board games*, and a Bo3 match is not linear in
game win rate. Chapin:

```
P(match) = p1 * (2q - q²) + (1 - p1) * q²
```
where `p1` = game-1 win rate, `q` = post-board game win rate. His worked cases,
which the implementation must reproduce exactly:

| p1 | q | P(match) |
|---:|---:|---:|
| 0.40 | 0.60 | 0.552 |
| 0.30 | 0.60 | 0.504 |
| 0.40 | 0.70 | 0.658 |

Magnitude, stated honestly: `dP/dq = 2·p1 + 2q(1 − 2·p1)`, which over realistic
inputs runs about 0.84–1.16. So the current flat bump is off by up to ~16%
relative, and in a direction that depends on `p1` — it overstates sideboard help
in matchups you already win game 1 and understates it where you are losing game
1. Real, but a refinement rather than a five-alarm bug. Do not oversell it in
the UI.

**Data constraint.** The 303,344 scraped rows are match-level only; `p1` and `q`
are not separately observable. Game-level data exists **only** in `match_log`
(109 rows, with `g1_result` / `g2_result` / `g3_result` / `play_draw`). So:

- Derive a global prior for `p1` from `match_log`, not a per-matchup value.
- Where a matchup has no game-level data, hold `p1 = observed match WR` and
  solve for the `q` implied by it, then apply the sideboard bump to `q` and
  recompose. Label that row's source so the UI can distinguish it.

**Implement.** New `analysis/match_math.py`:
```python
def match_winrate(p1: float, q: float) -> float
def required_q(p1: float, target_match_wr: float) -> float   # inverse solver
def implied_q(p1: float, observed_match_wr: float) -> float
```
`required_q` is the feature worth shipping: for each unfavourable matchup, show
**"to reach 50%, this sideboard plan has to get post-board games to X%."** That
is the number RC prep actually wants and nothing in the app produces it today.
Return `None` when the target is unreachable (`q` would exceed 1).

Wire into `compute_deck_ev`: apply the bump to `q`, recompose, and add
`required_q_for_even` to each row. Keep the old flat-bump path behind a
`use_match_math=False` flag for one release so the numbers can be compared.

Tests: the three worked cases above to 3dp, round-trip `implied_q` →
`match_winrate`, `required_q` returning `None` when unreachable, and boundary
behaviour at `p1` or `q` of 0 and 1.

---

## Task 4 — Chapin corpus into the existing strategy search

No new code. `scripts/ingest_strategy_docs.py` already chunks
`../mtg-sim/docs/*.md` on markdown headings and derives `(archetype, doc_type)`
from the filename suffix. Eleven files named `chapin_<domain>_rules_reference.md`
have been dropped into that corpus (one `##` heading per rule, page cite in the
heading, rule id in the body), so they ingest as `doc_type="rules"` with
`archetype="chapin_<domain>"`.

Run `python scripts/ingest_strategy_docs.py --counts` first to confirm the chunk
count looks sane before spending any Pinecone quota. No schema change needed.

---

## Explicitly out of scope

- **Cascade population dynamics.** `analysis/equilibrium.py` already has
  replicator dynamics, which strictly dominates Chapin's informal weekly-cascade
  model (`IC-12`). The only idea there worth stealing later is the switching-
  friction parameter `m` plus an inert sub-population (players who never switch
  because of collection or preference) — a two-parameter addition to
  `replicator_dynamics`, fittable from week-over-week share history. Not now.
- **Chapin's six-pillar deck scorer.** `analysis/chapin.py` already exists and
  does something different (deck construction scoring). Leave it alone; the new
  modules must not import it or collide with its name.

## Before committing

Per the repo rules: update `CLAUDE.md`, `NEXT_STEPS.md` and `ROADMAP.md`, then
`git push`. Run `pytest` — and after any scraper-adjacent change, verify output
with `--counts` rather than trusting the exit code.
