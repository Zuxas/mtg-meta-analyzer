"""Two-reviewer PR gate: Claude (Anthropic API) and Tom (OpenAI API).

Round 1: each reviewer independently reviews the diff and returns JSON findings.
Round 2: each reviewer cross-examines the OTHER reviewer's blocking findings
         (agree / disagree + reason).

Outcome:
  ready          both approve, nothing blocking, nothing disputed
  needs-changes  at least one blocking finding the other reviewer AGREED with
                 (or a blocking finding raised by both)
  needs-human    blocking findings exist but every one was disputed

Writes review.md (PR comment body) and review.json (machine result).

Env: ANTHROPIC_API_KEY, OPENAI_API_KEY, BASE_SHA, HEAD_SHA,
     CLAUDE_MODEL, OPENAI_MODEL, PR_TITLE, PR_BODY
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_DIFF_CHARS = 150_000
MAX_CONTEXT_CHARS = 8_000
BLOCKING = {"blocker", "major"}
MARKER = "<!-- claude-tom-gate -->"

SYSTEM = """You are a senior Python reviewer acting as a CI merge gate for mtg-meta-analyzer,
a PyQt6 + SQLite desktop app that scrapes and analyzes Magic: The Gathering tournament data.

Review ONLY the diff you are given. Focus on things that would hurt the user if merged:
correctness bugs, data loss or silent data corruption in the SQLite DB, schema or migration
breakage on fresh vs existing databases, wrong statistics (rates, win %, counts),
crashes on startup or empty data, concurrency/thread issues in Qt, security problems,
and tests that do not actually test what they claim.

Do NOT report style, naming, formatting, or speculative nice-to-haves.

Severity:
  blocker - will break the app, corrupt/lose data, or produce wrong numbers users rely on
  major   - real bug with a concrete failure scenario, but limited blast radius
  minor   - worth fixing, not worth blocking a merge

Every blocker/major MUST include a concrete failure scenario (inputs/state -> wrong result).
If you cannot name one, downgrade it to minor.

Reply with ONE JSON object and nothing else:
{"verdict": "approve" | "request_changes",
 "summary": "2-4 sentences",
 "findings": [{"id": "short-slug", "severity": "blocker|major|minor", "file": "path",
               "line": 0, "issue": "...", "scenario": "...", "fix": "..."}]}
verdict must be "request_changes" if and only if there is at least one blocker or major."""

CROSS = """Another reviewer raised the blocking findings below on the same diff.
For EACH one, decide whether it is a real problem in this diff. Check the diff yourself;
do not defer to the other reviewer. Reply with ONE JSON object and nothing else:
{"rulings": [{"id": "<their id>", "agree": true|false, "reason": "one or two sentences"}]}"""


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def build_payload() -> str:
    base, head = os.environ["BASE_SHA"], os.environ.get("HEAD_SHA", "HEAD")
    rng = f"{base}...{head}"
    log = git("log", "--format=- %h %s", f"{base}..{head}")
    stat = git("diff", "--stat", rng)
    diff = git("diff", "--no-color", "-U5", rng, "--", ".",
               ":(exclude)*.lock", ":(exclude)graphify-out/*")
    truncated = ""
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS]
        truncated = f"\n\n[DIFF TRUNCATED at {MAX_DIFF_CHARS} chars -- review what is shown; say so in summary]"
    ctx = ""
    for name in ("CLAUDE.md", "AGENTS.md"):
        p = Path(name)
        if p.exists():
            ctx = p.read_text(encoding="utf-8", errors="replace")[:MAX_CONTEXT_CHARS]
            break
    return (f"PR title: {os.environ.get('PR_TITLE','')}\n"
            f"PR description:\n{os.environ.get('PR_BODY','')[:4000]}\n\n"
            f"Project notes (truncated):\n{ctx}\n\n"
            f"Commits:\n{log}\nFiles:\n{stat}\n\nDiff:\n{diff}{truncated}")


def _json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"reviewer did not return JSON: {text[:300]}")
    return json.loads(m.group(0))


def ask_claude(system: str, user: str) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("CLAUDE_MODEL") or "claude-opus-4-5",
        max_tokens=8000, system=system,
        messages=[{"role": "user", "content": user}])
    return _json("".join(b.text for b in msg.content if getattr(b, "type", "") == "text"))


def ask_tom(system: str, user: str) -> dict:
    from openai import OpenAI
    client = OpenAI()
    resp = client.responses.create(
        model=os.environ.get("OPENAI_MODEL") or "gpt-5",
        instructions=system, input=user,
        text={"format": {"type": "json_object"}})
    return _json(resp.output_text)


REVIEWERS = {"Claude": ask_claude, "Tom": ask_tom}


def blocking(review: dict) -> list[dict]:
    return [f for f in review.get("findings", []) if f.get("severity") in BLOCKING]


def main() -> int:
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BASE_SHA"):
        if not os.environ.get(k):
            print(f"Missing {k}. Add it as a repository secret (Settings > Secrets and variables > Actions).")
            return 2
    payload = build_payload()

    # Round 1 -- independent reviews, in parallel.
    with cf.ThreadPoolExecutor(2) as ex:
        futs = {n: ex.submit(fn, SYSTEM, payload) for n, fn in REVIEWERS.items()}
        r1 = {n: f.result() for n, f in futs.items()}

    # Round 2 -- cross-examination of the other side's blocking findings.
    other = {"Claude": "Tom", "Tom": "Claude"}
    rulings: dict[str, dict[str, dict]] = {"Claude": {}, "Tom": {}}  # raiser -> id -> ruling
    jobs = {}
    with cf.ThreadPoolExecutor(2) as ex:
        for judge, raiser in other.items():
            bl = blocking(r1[raiser])
            if bl:
                q = payload + "\n\n" + CROSS + "\n\nFindings:\n" + json.dumps(bl, indent=1)
                jobs[raiser] = ex.submit(REVIEWERS[judge], "You are a careful, skeptical code reviewer.", q)
        for raiser, fut in jobs.items():
            for r in fut.result().get("rulings", []):
                rulings[raiser][str(r.get("id"))] = r

    confirmed, disputed = [], []
    for raiser in REVIEWERS:
        for f in blocking(r1[raiser]):
            ruling = rulings[raiser].get(str(f.get("id")), {"agree": False, "reason": "no ruling returned"})
            item = {**f, "raised_by": raiser, "ruling": ruling}
            (confirmed if ruling.get("agree") else disputed).append(item)

    if confirmed:
        outcome = "needs-changes"
    elif disputed:
        outcome = "needs-human"
    else:
        outcome = "ready"

    Path("review.json").write_text(json.dumps(
        {"outcome": outcome, "round1": r1, "confirmed": confirmed, "disputed": disputed}, indent=1))
    Path("review.md").write_text(render(outcome, r1, confirmed, disputed), encoding="utf-8")
    print(f"Outcome: {outcome}  (confirmed={len(confirmed)}, disputed={len(disputed)})")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"outcome={outcome}\n")
    return 0


def _fmt(f: dict) -> str:
    loc = f"`{f.get('file','?')}:{f.get('line','?')}`"
    s = f"- **[{f.get('severity','?')}] {f.get('id','')}** {loc} — {f.get('issue','')}"
    if f.get("scenario"):
        s += f"\n  - Failure: {f['scenario']}"
    if f.get("fix"):
        s += f"\n  - Fix: {f['fix']}"
    if f.get("ruling"):
        other = "Tom" if f.get("raised_by") == "Claude" else "Claude"
        verdict = "agrees" if f["ruling"].get("agree") else "disputes"
        s += f"\n  - Raised by {f['raised_by']}; {other} {verdict}: {f['ruling'].get('reason','')}"
    return s


def render(outcome, r1, confirmed, disputed) -> str:
    head = {"ready": "✅ **Ready to merge** — tests, data-safety and DB checks passed; Claude and Tom both approve.",
            "needs-changes": "❌ **Needs changes** — at least one blocking finding was confirmed by both reviewers.",
            "needs-human": "⚠️ **Needs your call** — blocking findings were raised but the other reviewer disputed them."}[outcome]
    out = [MARKER, "## Claude + Tom review gate", "", head, ""]
    if confirmed:
        out += ["### Confirmed blocking findings", *[_fmt(f) for f in confirmed], ""]
    if disputed:
        out += ["### Disputed findings (your call)", *[_fmt(f) for f in disputed], ""]
    for name, rev in r1.items():
        minors = [f for f in rev.get("findings", []) if f.get("severity") not in BLOCKING]
        out += [f"<details><summary><b>{name}</b>: {rev.get('verdict','?')}</summary>", "",
                rev.get("summary", ""), ""]
        if minors:
            out += ["Minor notes:", *[_fmt(f) for f in minors]]
        out += ["", "</details>", ""]
    sha = os.environ.get("HEAD_SHA", "")[:7]
    out.append(f"<sub>Reviewed at {sha}. Re-runs on every push.</sub>")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
