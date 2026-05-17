# Single-Instance Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse second-launch `python run_gui.py` attempts cleanly via QLockFile, with a 30s stale-lock TTL that auto-recovers from crashes.

**Architecture:** New `gui/single_instance.py` module wrapping `QLockFile` from `PyQt6.QtCore`. `run_gui.py` instantiates QApplication first (needed for the modal error dialog), tries to acquire the lock, exits with a dialog on failure, and wires `release()` to `aboutToQuit` for clean shutdown.

**Tech Stack:** Python 3.13, PyQt6 (QtCore.QLockFile, QtWidgets.QMessageBox), pytest.

**Spec:** `docs/superpowers/specs/2026-05-16-single-instance-enforcement-design.md`

**Baseline:** commit `dace012`, 185/185 tests green after Phase 2 of the puzzle tool.

**Ship target:** tonight (2026-05-16). 3 tasks, ~1-2h total.

---

## Critical lessons baked in

1. **QApplication MUST exist before `acquire()`** — we use QMessageBox for the "already running" dialog, which needs an event loop. Order matters in `run_gui.py`.
2. **Tests use `tmp_path` fixture** — never touch the real `data/.run_gui.lock` path; would clobber the user's running app.
3. **Lazy-create QLockFile inside `acquire()`** — so monkeypatching `_lock_path` in tests works even after instance construction.
4. **`QLockFile` is QtCore** — no QApplication required for unit tests.

---

## File Structure

**Create:**
- `gui/single_instance.py` — `SingleInstanceLock` class (~60 lines)
- `tests/test_single_instance.py` — 6 unit tests (~80 lines)

**Modify:**
- `run_gui.py:52-81` — add lock acquire/release wiring (~12 lines inserted)
- `CLAUDE.md` — add single-instance line to §9 Critical Implementation Notes
- `NEXT_STEPS.md` — strike-through the "Single-instance enforcement" bullet under the 5/16 chain

---

## Task 1: SingleInstanceLock class + tests

**Files:**
- Create: `gui/single_instance.py`
- Create: `tests/test_single_instance.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_single_instance.py`:

```python
"""Tests for gui/single_instance.py — QLockFile wrapper for
enforcing one running instance of the GUI."""
from pathlib import Path

import pytest


def test_acquire_returns_true_on_first_call(tmp_path):
    """Fresh lock path: first acquire succeeds."""
    from gui.single_instance import SingleInstanceLock
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    assert lock.acquire() is True
    lock.release()


def test_acquire_returns_false_when_held(tmp_path):
    """Two SingleInstanceLock instances pointing at the same path:
    the second acquire() must return False."""
    from gui.single_instance import SingleInstanceLock
    path = tmp_path / ".test.lock"
    lock_a = SingleInstanceLock(lock_path=path)
    lock_b = SingleInstanceLock(lock_path=path)
    assert lock_a.acquire() is True
    assert lock_b.acquire() is False
    lock_a.release()


def test_release_allows_reacquire(tmp_path):
    """release() then acquire() on the same instance succeeds."""
    from gui.single_instance import SingleInstanceLock
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    assert lock.acquire() is True
    lock.release()
    assert lock.acquire() is True
    lock.release()


def test_release_is_idempotent(tmp_path):
    """release() can be called repeatedly without error.
    Important: wired to QApplication.aboutToQuit, may fire alongside
    explicit cleanup calls."""
    from gui.single_instance import SingleInstanceLock
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    lock.acquire()
    lock.release()
    lock.release()  # no-op
    lock.release()  # no-op
    # No exception raised


def test_is_held_reflects_state(tmp_path):
    """is_held() returns the current ownership state."""
    from gui.single_instance import SingleInstanceLock
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    assert lock.is_held() is False
    lock.acquire()
    assert lock.is_held() is True
    lock.release()
    assert lock.is_held() is False


def test_creates_parent_dir_if_missing(tmp_path):
    """Lock path with a not-yet-existing parent directory: should
    mkdir -p before attempting the lock. Solves the case where data/
    doesn't exist on a fresh clone."""
    from gui.single_instance import SingleInstanceLock
    nested = tmp_path / "deep" / "nested" / ".test.lock"
    lock = SingleInstanceLock(lock_path=nested)
    assert lock.acquire() is True
    assert nested.parent.exists()
    lock.release()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_single_instance.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'gui.single_instance'`.

- [ ] **Step 3: Implement `gui/single_instance.py`**

Create the file:

```python
"""Single-instance enforcement for the MTG Meta Analyzer GUI.

Wraps Qt's QLockFile to refuse second-launch attempts. The lock file
lives at <project_root>/data/.run_gui.lock by default with a 30-second
stale-lock TTL — if a previous process died ungracefully, the lock
self-heals after 30s so the user isn't permanently locked out.

QApplication does NOT need to exist before constructing a
SingleInstanceLock — QLockFile is QtCore, not QtWidgets. However,
the calling code (run_gui.py) DOES need QApplication before showing
the "already running" dialog, so the call order in run_gui.py is:

    app = QApplication(sys.argv)        # FIRST
    lock = SingleInstanceLock()
    if not lock.acquire():
        # show dialog, exit
        ...
    app.aboutToQuit.connect(lock.release)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QLockFile


_DEFAULT_LOCK_NAME = ".run_gui.lock"
_STALE_LOCK_TTL_MS = 30_000  # 30 seconds
_ACQUIRE_TIMEOUT_MS = 100    # don't block startup if lock is held


def _default_lock_path() -> Path:
    """<project_root>/data/.run_gui.lock — project root resolved
    relative to this file."""
    return (
        Path(__file__).resolve().parent.parent / "data" / _DEFAULT_LOCK_NAME
    )


class SingleInstanceLock:
    """QLockFile wrapper for single-instance enforcement.

    Usage:
        lock = SingleInstanceLock()
        if not lock.acquire():
            # show error dialog, sys.exit(1)
            ...
        # ... app runs ...
        lock.release()  # or wire to QApplication.aboutToQuit
    """

    def __init__(self, lock_path: Optional[Path] = None):
        """lock_path defaults to <project_root>/data/.run_gui.lock.
        Override for tests (use tmp_path)."""
        self._lock_path: Path = Path(lock_path) if lock_path else _default_lock_path()
        self._qlock: Optional[QLockFile] = None
        self._held: bool = False

    def acquire(self) -> bool:
        """Try to acquire the lock with a 100ms wait. Returns True if
        held by this process, False if another process holds it.

        Lazily creates the QLockFile and ensures the parent directory
        exists. Setting the stale-lock TTL means the lock auto-clears
        30s after an ungraceful previous-process exit."""
        # mkdir -p the parent directory (covers fresh-clone case where
        # data/ doesn't exist yet)
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Lazy-create so tests can monkeypatch _lock_path after construction
        if self._qlock is None:
            self._qlock = QLockFile(str(self._lock_path))
            self._qlock.setStaleLockTime(_STALE_LOCK_TTL_MS)

        result = self._qlock.tryLock(_ACQUIRE_TIMEOUT_MS)
        self._held = bool(result)
        return self._held

    def release(self) -> None:
        """Release the lock if held. Safe to call repeatedly."""
        if self._qlock is not None and self._held:
            self._qlock.unlock()
        self._held = False

    def is_held(self) -> bool:
        """Whether this instance currently holds the lock."""
        return self._held
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_single_instance.py -v
```

Expected: PASS (6 passed).

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: 191 passed (was 185 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add gui/single_instance.py tests/test_single_instance.py
git commit -m "feat(single-instance): SingleInstanceLock class wrapping QLockFile + 6 tests"
```

---

## Task 2: Wire `run_gui.py` to enforce the lock

**Files:**
- Modify: `run_gui.py` (insert ~12 lines after the QApplication construction at line 52)

- [ ] **Step 1: Read the current `run_gui.py` startup block**

```bash
python -c "print(open('run_gui.py').read()[:2500])"
```

The relevant existing structure (around lines 50-81):

```python
from gui.main_window import MainWindow

app = QApplication(sys.argv)
app.setApplicationName("MTG Meta Analyzer")
app.setOrganizationName("MTGMeta")
# ... (more setup) ...

# Stop all workers cleanly before the process exits
app.aboutToQuit.connect(window.cleanup)

sys.exit(app.exec())
```

Confirm the line numbers haven't drifted (Phase 2 work may have shifted them).

- [ ] **Step 2: Add the import at the top of `run_gui.py`**

Find the imports block (near other `from gui.*` imports). Add:

```python
from gui.single_instance import SingleInstanceLock
```

Use Edit with `old_string="from gui.main_window import MainWindow"` and `new_string="from gui.single_instance import SingleInstanceLock\nfrom gui.main_window import MainWindow"` (or wherever it lands alphabetically — group with other `from gui.*` imports).

- [ ] **Step 3: Insert the lock acquire block right after `app = QApplication(sys.argv)`**

Use Edit to replace:

```python
app = QApplication(sys.argv)
app.setApplicationName("MTG Meta Analyzer")
app.setOrganizationName("MTGMeta")
```

with:

```python
app = QApplication(sys.argv)
app.setApplicationName("MTG Meta Analyzer")
app.setOrganizationName("MTGMeta")

# Single-instance enforcement: refuse second-launch attempts
_instance_lock = SingleInstanceLock()
if not _instance_lock.acquire():
    from PyQt6.QtWidgets import QMessageBox
    QMessageBox.critical(
        None,
        "MTG Meta Analyzer already running",
        "Another instance is already running.\n\n"
        "Check the system tray (bottom-right corner of your taskbar) "
        "for the Team Resolve icon.\n\n"
        "If the existing window is unresponsive, use Ctrl+Shift+Q on "
        "it to force-quit, then wait 30 seconds before relaunching.",
    )
    sys.exit(1)
```

- [ ] **Step 4: Wire the release to `aboutToQuit`**

Use Edit to replace:

```python
# Stop all workers cleanly before the process exits
app.aboutToQuit.connect(window.cleanup)
```

with:

```python
# Stop all workers cleanly before the process exits
app.aboutToQuit.connect(window.cleanup)
app.aboutToQuit.connect(_instance_lock.release)
```

- [ ] **Step 5: Smoke-test the wiring with a headless import**

```bash
QT_QPA_PLATFORM=offscreen python -c "
import sys
sys.argv = ['run_gui.py', '--help']
import run_gui  # confirms no import-time errors
print('OK')
"
```

Expected: `OK`. If `run_gui` short-circuits on `--help` or similar, just confirm the module imports without exception.

If the file doesn't have a `__main__` guard around the launch logic, this step may actually launch the GUI — in that case skip Step 5 and rely on Step 6's manual smoke.

- [ ] **Step 6: Manual smoke test — first launch should work**

```bash
python run_gui.py
```

Expected: GUI launches normally. Confirm by checking the tray icon appears.

- [ ] **Step 7: Manual smoke test — second launch should refuse**

While the first instance is still running, in a second terminal:

```bash
python run_gui.py
```

Expected: a `QMessageBox` titled "MTG Meta Analyzer already running" appears, user clicks OK, second process exits with code 1. Confirm:

```bash
# in the second terminal, after the dialog closes
echo $LASTEXITCODE  # PowerShell — should be 1
```

Or on bash/git-bash: `echo $?` → `1`.

- [ ] **Step 8: Manual smoke test — clean exit + relaunch**

Close the first GUI instance via the X button (or tray Quit). Wait 1 second.

```bash
python run_gui.py
```

Expected: GUI launches normally (lock was released on `aboutToQuit`).

- [ ] **Step 9: Run full test suite — confirm no regressions**

```bash
python -m pytest tests/ -q --tb=line | tail -3
```

Expected: 191 passed.

- [ ] **Step 10: Commit**

```bash
git add run_gui.py
git commit -m "feat(single-instance): wire SingleInstanceLock to run_gui.py startup + aboutToQuit"
```

---

## Task 3: Docs + crash-test smoke + push

**Files:**
- Modify: `CLAUDE.md` (add single-instance line to §9 Critical Implementation Notes)
- Modify: `NEXT_STEPS.md` (mark single-instance done in the 5/16 chain section)

- [ ] **Step 1: Crash-test smoke (verify stale-lock TTL works)**

Launch the GUI:

```bash
python run_gui.py
```

Then in PowerShell, find the process and force-kill it (skipping the `aboutToQuit` cleanup):

```powershell
Get-Process python | Where-Object { $_.MainWindowTitle -like "*MTG Meta*" } | Stop-Process -Force
```

(Or use Task Manager — the goal is to bypass the cleanup hook so the lock file stays behind.)

Immediately attempt to relaunch:

```bash
python run_gui.py
```

Expected: dialog appears ("MTG Meta Analyzer already running") because the lock is still on disk and not yet stale.

Wait 31 seconds. Attempt to relaunch again:

```bash
python run_gui.py
```

Expected: GUI launches normally (QLockFile detected the stale lock and let us through). If this fails, the stale-lock TTL isn't working — investigate `setStaleLockTime` placement.

- [ ] **Step 2: Update CLAUDE.md §9**

Find the `## 9. CRITICAL IMPLEMENTATION NOTES` section. Add a new subsection:

```markdown
### Single-instance enforcement
`gui/single_instance.py::SingleInstanceLock` wraps `QLockFile` with a 30s stale-lock TTL. `run_gui.py` acquires at startup (after `QApplication(sys.argv)` since the error dialog needs an event loop) and releases via `aboutToQuit`. Lock at `data/.run_gui.lock` (gitignored). A second launch attempt shows a `QMessageBox` and exits with code 1. After an ungraceful crash, wait ~30s for the stale-lock to clear before relaunching.
```

Place it after the existing "### Worker lifecycle" subsection.

- [ ] **Step 3: Update CLAUDE.md "Last updated" line**

Find line 3:

```markdown
Last updated: 2026-05-16 (puzzle tool Phase 2 shipped — scanner + Inbox + Author)
```

Replace with:

```markdown
Last updated: 2026-05-16 (puzzle tool Phase 2 + single-instance enforcement shipped)
```

- [ ] **Step 4: Update NEXT_STEPS.md**

Find the 5/16 chain section. Strike through item 3:

```markdown
3. **Single-instance enforcement** — QLockFile + stale-lock detection
   so multiple `python run_gui.py` invocations don't accumulate
   (saw 4 zombies on 5/15 before the smart-X fix).
```

Replace with:

```markdown
3. ~~**Single-instance enforcement**~~ ✓ shipped (`gui/single_instance.py` + QLockFile, 30s stale TTL). Second launch shows clean error dialog. Crash-test verified.
```

- [ ] **Step 5: Commit + push**

```bash
git add CLAUDE.md NEXT_STEPS.md
git commit -m "docs(single-instance): note QLockFile pattern in CLAUDE.md + check off the 5/16 chain item"
git push
```

If the pre-push hook rejects the commit (see `[[feedback_pre-push-hook-path-scrubbing]]` and `[[feedback_no-user-handles-in-docs]]`), scrub the offending content and create a NEW commit (not `--amend`).

---

## Validation gates (mechanical)

Single-instance is "shipped" when ALL of these are true:

- [ ] `python -m pytest tests/test_single_instance.py -v` → 6 passed
- [ ] `python -m pytest tests/` → 191 passed (was 185)
- [ ] Manual smoke: first launch OK, second launch shows dialog + exits 1
- [ ] Manual smoke: close + relaunch works cleanly
- [ ] Crash-test: force-kill + immediate relaunch sees dialog; relaunch after 31s succeeds
- [ ] `git push` succeeds

---

## What this does NOT do (intentional scope limits)

- No "focus existing window on second launch" UX (would need QLocalSocket IPC — deferred)
- No crash-recovery state restore (different problem, separate spec if needed)
- No health-monitoring panel (covered in the alternative scope option, deferred)
- No endurance-test automation (manual checklist task, not code)
- No cross-machine locking (single-user, single-Windows-box project)
- No "multiple clones run independently" prevention — that's the correct dev behavior
