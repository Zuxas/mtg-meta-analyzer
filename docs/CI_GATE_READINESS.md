# CI gate — readiness review (status: PAUSED, not proposed)

Branch `ci/claude-tom-gate` is a backup only. No PR is open, no secrets are set, no paid
review has ever run. Pushing to this branch does not trigger the workflow: `gate.yml`
triggers on PRs **into** `main`, pushes **to** `main`, and `workflow_dispatch` (which
GitHub only offers for workflows present on the default branch). It stays inert until
merged to `main`.

Each item below states what the branch does **today** (`7d85d55`) and what must change
before it is proposed again. Items marked **GAP** are not satisfied today.

## 1. What is sent to Anthropic and OpenAI

`scripts/ci/ai_review.py` builds ONE text payload and sends the same payload to both:

| Content | Source | Limit |
|---|---|---|
| PR title and body | GitHub event | body truncated to 4,000 chars |
| First 8,000 chars of `CLAUDE.md` (or `AGENTS.md`) | head checkout | 8,000 chars |
| `git log` one-line subjects, base..head | repo | unbounded (**GAP**: cap it) |
| `git diff --stat` | repo | unbounded (**GAP**: cap it) |
| `git diff -U5` of every changed file except `*.lock`, `graphify-out/*` | repo | 150,000 chars, then hard cut |

Round 2 re-sends the whole payload plus the other reviewer's blocking findings.

Not sent: secrets, `config.ini`, databases, files outside the diff. **But** anything a
commit adds — including a mistakenly committed data file — is in the diff. The safety
guard runs first, and the review job `needs:` the tests and DB jobs, which `needs:` the
safety job, so a blocked file stops the run before any API call. **GAP**: add an explicit
pathspec allowlist (`*.py`, `*.md`, `*.yml`, `*.json` under `scripts/`, `tests/`) so the
payload never depends on the guard alone. Note: `CLAUDE.md` is project notes — confirm
nothing personal is in its first 8,000 chars before enabling.

## 2. Expected cost and request limits

Per PR push (not per PR): 2 requests in round 1, 0–2 in round 2 → **2–4 requests**.
Input per request ≈ payload size: a 150k-char diff ≈ 35–40k tokens; typical PRs here are
5–30k tokens. Output: Claude capped at 8,000 tokens; **GAP**: OpenAI call has no
`max_output_tokens` — add one (e.g. 8,000).
Cost = requests × (input tokens × input price + output tokens × output price) for the
chosen models; check current list prices before enabling — they are not hard-coded here.
**GAP**: no per-day/per-PR budget. Add: skip the review when the diff exceeds the cap
instead of truncating; run review only on `ready_for_review`/label, not every push;
`concurrency` already cancels superseded runs.

## 3. Behaviour when secrets are absent

Today: `ai_review.py` prints which secret is missing and exits 2 → review job fails →
label job sets `needs-human`. No API call is attempted. Fork PRs never receive secrets
(see 4), so they would always land here. **Change**: exit 0 with a "review skipped: no
secrets" comment and no label, so a missing key is visible but not a failure.

## 4. Forked PRs

Trigger is `pull_request` (not `pull_request_target`), so fork PRs run with a read-only
`GITHUB_TOKEN` and **no secrets**. Tests, safety and DB jobs work; the review is skipped
per 3; the label/comment steps **fail** on forks (read-only token). **Change**: guard
review + label jobs with
`if: github.event.pull_request.head.repo.full_name == github.repository`. Fork PRs are
then "tests only", which is the intended support level.

## 5. Minimal token permissions

Today: workflow-level `contents: read, pull-requests: write, issues: write` — every job
gets write. **GAP**. Change to workflow-level `permissions: {}` and per job:
`safety`/`tests`/`db-compat`: `contents: read`; `review`: `contents: read`,
`pull-requests: write` (sticky comment); `label`: `issues: write`, `pull-requests: read`
(labels are issue-scoped). Label creation needs `issues: write`.

## 6. `pull_request_target` / untrusted checkout

`pull_request_target` is not used and must never be: it runs with secrets and a write
token in the base-repo context, and checking out the PR head there executes attacker code
with those credentials. With `pull_request`, the head checkout runs with no secrets on
forks. Rule for any future change: never combine `pull_request_target` or
`workflow_run` with `actions/checkout` of `github.event.pull_request.head.sha`. The
`db-compat` job runs PR code (tests, app start) — acceptable only because it holds no
secrets and a read-only token (after item 5).

## 7. Actions pinned to commit SHAs

**GAP**. Today: `actions/checkout@v5`, `actions/setup-python@v6`,
`actions/github-script@v8`, `actions/upload-artifact@v4` — mutable tags. Change each to
`uses: owner/action@<40-char SHA> # vX.Y.Z`, resolved from the action's release page at
the time of change, and let Dependabot (`package-ecosystem: github-actions`) propose
bumps. The existing `ci.yml` / `tests.yml` have the same gap.

## 8. Timeouts and maximum diff size

**GAP**: no `timeout-minutes` on any job (GitHub default: 360). Set: safety 5, tests 20,
db-compat 15, review 10, label 3. Script level: `db_compat.py` has a 90–120 s in-process
watchdog and a 600 s subprocess timeout; `ai_review.py` has **no** HTTP timeout — pass
`timeout=120` to both SDK clients and `max_retries=2`.
Diff cap: 150,000 chars, truncated with a note. Change to: over the cap → skip review,
label `needs-human`, comment "diff too large for automated review".

## 9. Model output is never executed

Model output is parsed with `json.loads` and only rendered into a Markdown comment via
`github-script` (`issues.createComment`/`updateComment` body). It is never passed to a
shell, `eval`, `exec`, `subprocess`, a file path, or a `run:` step; `PR_TITLE`/`PR_BODY`
reach Python through `env:`, not `${{ }}` interpolation in `run:`, so they cannot inject
shell. The only effect of model output is the label choice, mapped from a fixed enum
(`ready` / `needs-changes` / `needs-human`). Keep it that way: no "suggested fix" may ever
be applied automatically.
**Residual risk**: prompt injection via PR content can bias the verdict. Mitigated by the
label never merging anything and by the trial period (10).

## 10. Non-blocking trial period

Before it may gate merges:
1. Land with the review job `continue-on-error: true` and the label job writing
   `ai-review: <outcome>` (informational) instead of `ready-to-merge`.
2. No branch-protection rule references it.
3. Run on N ≥ 10 real PRs; record per PR: verdict, confirmed/disputed findings, whether
   each was a true positive, tokens used, cost.
4. Promote only if: zero data-safety misses, false-positive blocking rate acceptable to
   the repo owner, cost within an agreed monthly cap.
5. Review, tests, safety and DB jobs can be adopted separately — the non-AI jobs have no
   cost and can gate sooner.

## Approvals still needed from the repo owner

API keys and which models; monthly cost cap; whether `CLAUDE.md` may be sent; trial
length; and, separately, whether any scheduled audit should exist (schedule, data access,
notification destination, cost).
