# Claude + Tom CI gate

`.github/workflows/gate.yml` runs on every PR to `main` and every push to `main`.

| Job | What it proves | Script |
|---|---|---|
| Data-safety guard | No DBs, backups, caches, evidence, manifests, secrets, or personal paths in the change | `scripts/ci/check_safety.py` |
| Test suite | `pytest -m "not live_db and not network"` passes on Ubuntu / Python 3.12 | — |
| DB compatibility | Fresh DB gets every required table; a DB built by the **base** commit upgrades without losing rows; `save_matches` works on both; re-running startup changes nothing | `scripts/ci/db_compat.py` |
| App start | `MainWindow` opens and closes on an empty DB (first-run dialogs are dismissed and logged) | `scripts/ci/db_compat.py app` |
| Claude + Tom review | PRs only, after the above pass. Both review the diff independently, then cross-examine each other's blocking findings | `scripts/ci/ai_review.py` |

## Result label (never auto-merges)

- `ready-to-merge` — every check passed and neither reviewer has a blocking finding.
- `needs-changes` — a check failed, or a blocking finding was **confirmed** by the other reviewer.
- `needs-human` — blocking findings exist but the other reviewer **disputed** each one (or the review could not run).

One sticky PR comment holds the latest review and is updated on every push.

## Setup (once)

Repo **Settings → Secrets and variables → Actions**:

- Secrets: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- Variables (optional): `CLAUDE_MODEL`, `OPENAI_MODEL` — defaults are in `ai_review.py`

## Adding tables

If a branch adds tables that startup must create (e.g. `matches_excluded`,
`excluded_events`), add them to `scripts/ci/db_contract.json` in the same PR.
CI only uses the real startup path (`init_db` + `save_matches`); it never
creates tables itself, so a missing `ensure` call fails the gate.

## Run locally

```
python scripts/ci/check_safety.py --base origin/main --head HEAD
python scripts/ci/db_compat.py fresh --dir %TEMP%\ci_fresh
python scripts/ci/db_compat.py app   --dir %TEMP%\ci_app
```
