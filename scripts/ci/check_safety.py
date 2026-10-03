"""Data-safety guard for the CI gate.

Fails if a change set adds or modifies anything that must never be committed:
live databases, backups, raw caches, evidence files, manifests, secrets,
config with keys, or personal paths in added lines.

Usage:
    python scripts/ci/check_safety.py --base <sha> --head <sha>
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys

MAX_BYTES = 2 * 1024 * 1024  # anything bigger than 2 MB is almost certainly data

# Paths that must never be committed (glob, matched against the repo path).
BLOCKED_PATHS = [
    "*.db", "*.db-*", "*.db.*", "*.sqlite", "*.sqlite3",
    "*.bak", "*.bak-*", "*.bak.*", "*backup*/*", "backups/*", "*/backups/*",
    "config.ini", ".env", ".env.*", "*cookies*.txt",
    "logs/*", "*.log",
    "data/cache/*", "*/raw_cache/*", "raw_cache/*", "cache/*", "data/raw/*",
    "*evidence*/*", "evidence/*",
    "*manifest*.json", "*manifest*.jsonl",
    "data/*.json", "data/*.csv", "data/*.parquet", "data/untapped/*",
    "data/match_replays/*", "data/preferences.json*",
]
# Explicit allowlist (checked before the block list).
ALLOWED_PATHS = [
    "tests/fixtures/*", "tests/data/*", "docs/*", "*.md",
    "config.example.ini", "*.template",
    "data/sb_matrices/*",   # curated sideboard matrices, committed on purpose
]

# Patterns that must not appear in ADDED lines.
LINE_RULES = [
    ("Windows user path", re.compile(r"[A-Za-z]:\\\\?Users\\\\?[A-Za-z0-9._-]+", re.I)),
    ("local project path", re.compile(r"vscode ai project", re.I)),
    ("macOS/Linux home path", re.compile(r"/(?:Users|home)/(?!runner\b)[a-z0-9._-]{2,}/", re.I)),
    ("Anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")),
    ("OpenAI key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("AWS key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("Pinecone key", re.compile(r"pcsk_[A-Za-z0-9_]{20,}")),
]
# Files whose added lines are not scanned (this file contains the patterns).
LINE_SCAN_SKIP = ["scripts/ci/check_safety.py"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def _match(path: str, patterns: list[str]) -> bool:
    p = path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p.lower(), pat) for pat in patterns)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", default="HEAD")
    a = ap.parse_args()

    rng = f"{a.base}...{a.head}"
    problems: list[str] = []

    # 1. Paths and sizes of added / modified / renamed / copied files.
    for line in git("diff", "--name-status", "--no-renames", "--diff-filter=ACMR", rng).splitlines():
        status, path = line.split("\t", 1)
        if not _match(path, ALLOWED_PATHS) and _match(path, BLOCKED_PATHS):
            problems.append(f"BLOCKED FILE  {path}  (data, backup, cache, evidence, manifest or secret file)")
            continue
        try:
            size = int(git("cat-file", "-s", f"{a.head}:{path}").strip())
        except subprocess.CalledProcessError:
            continue
        if size > MAX_BYTES:
            problems.append(f"TOO LARGE     {path}  ({size/1024/1024:.1f} MB > {MAX_BYTES/1024/1024:.0f} MB)")

    # 2. Secrets / personal paths in added lines.
    current = None
    lineno = 0
    for raw in git("diff", "-U0", "--no-color", rng).splitlines():
        if raw.startswith("+++ "):
            current = raw[6:] if raw.startswith("+++ b/") else None
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
            continue
        if current is None or current in LINE_SCAN_SKIP:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            text = raw[1:]
            for name, rx in LINE_RULES:
                if rx.search(text):
                    problems.append(f"{name.upper():<22} {current}:{lineno}")
            lineno += 1

    if problems:
        print("Data-safety guard FAILED:\n")
        for p in problems:
            print("  " + p)
        print("\nRemove these from the commit (or scrub the line) and push again.")
        return 1
    print("Data-safety guard passed: no data files, secrets or personal paths in this change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
