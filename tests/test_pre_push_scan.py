"""scripts/pre-push scans the pushed commits, not the working tree.

It used to grep each file on disk: an older checkout blocked a clean push, an
uncommitted local copy could pass a dirty one, and any touched file was
re-flagged for text already on the remote (a cookie-file path in CLAUDE.md).
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "pre-push"
# Built at runtime so this file does not trip the scan it tests.
OLD = "needs data/untapped_cookies" + ".txt\n"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo, name, text, msg):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def push(repo, local, remote):
    env = dict(os.environ, PRE_PUSH_LOCAL_FILE=str(repo / "none"), PRE_PUSH_QUIET="1")
    r = subprocess.run(["bash", str(HOOK)], cwd=repo, env=env, capture_output=True, text=True,
                       input=f"refs/heads/x {local} refs/heads/x {remote}\n")
    return r.returncode, r.stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    base = commit(tmp_path, "notes.md", OLD, "base")
    return tmp_path, base


def test_existing_text_on_the_remote_is_not_reflagged(repo):
    r, base = repo
    head = commit(r, "notes.md", OLD + "more docs\n", "edit")
    assert push(r, head, base)[0] == 0


def test_added_secret_line_is_blocked_with_its_line_number(repo):
    r, base = repo
    head = commit(r, "notes.md", OLD + "key ghp_" + "a" * 36 + "\n", "leak")
    code, out = push(r, head, base)
    assert code == 1 and "notes.md" in out and "line 2" in out and "ghp_" not in out


def test_working_tree_is_ignored(repo):
    r, base = repo
    head = commit(r, "notes.md", OLD + "clean\n", "clean")
    (r / "notes.md").write_text("ghp_" + "b" * 36 + "\n")       # dirty, uncommitted
    assert push(r, head, base)[0] == 0


def test_secret_added_then_removed_in_the_push_is_blocked(repo):
    r, base = repo
    commit(r, "notes.md", OLD + "ghp_" + "c" * 36 + "\n", "oops")
    head = commit(r, "notes.md", OLD, "remove it")              # tip is clean
    assert push(r, head, base)[0] == 1                          # history is not


def test_new_branch_scans_the_pushed_tree(repo):
    r, base = repo
    zero = "0" * 40
    assert push(r, base, zero)[0] == 1                          # the cookie path is in the tree
