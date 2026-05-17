# Single-Instance Enforcement — Design Spec

**Date:** 2026-05-16
**Author:** local user handle
**Status:** Approved (pre-implementation)

---

## Problem

Multiple `python run_gui.py` invocations accumulate as separate processes, each holding their own connection to `data/mtg_meta.db`, their own Win32 hotkey registrations, their own tray icons, and their own file locks on `preferences.json`. Observed on 2026-05-15 — four zombie GUI processes were found after a smoke session, each consuming ~300-500 MB RAM and competing for the same hotkey combos.

Side effects of multi-instance:
1. **Hotkey collisions** — Win32 `RegisterHotKey` is process-scoped; first launcher wins, later launchers silently fail to register. User loses Ctrl+Shift+M / Ctrl+Shift+L / Ctrl+Shift+Q on the new window.
2. **`preferences.json` corruption** — concurrent writes from two instances race the truncate+write+fsync pattern. Already saw this once.
3. **Tray icon stacking** — multiple Team Resolve icons in the tray, each connected to a different process.
4. **MTGA log watcher races** — both processes tail `Player.log`, both try to insert the same matches.
5. **Memory pressure** — 4 instances × ~400 MB = 1.6 GB for nothing.

## Goal

Enforce one running instance at a time. If a second launch attempt happens, refuse cleanly with a dialog telling the user the app is already running (and to check the system tray).

**Non-goals (deferred):**
- "Focus existing window on second launch" UX (would require QLocalSocket IPC — nice but not RC-critical).
- Cross-machine locking (Windows-only project, single-user).
- Per-user-account locking (single-user box).

## Architecture

One new module + small wiring change in `run_gui.py`.

```
gui/single_instance.py
  └─ class SingleInstanceLock
       ├─ acquire() -> bool
       ├─ release() -> None
       └─ is_held() -> bool

run_gui.py (modified)
  ├─ QApplication(sys.argv) — instantiated FIRST
  ├─ lock = SingleInstanceLock()
  ├─ if not lock.acquire():
  │     QMessageBox.critical(...) and sys.exit(1)
  ├─ app.aboutToQuit.connect(lock.release)
  └─ ... existing startup continues
```

### Lock file location

`data/.run_gui.lock` — relative to project root.

- `data/` is already gitignored.
- Hidden filename (leading `.`) to keep it from cluttering directory listings.
- One per project root; if the user clones the repo twice and runs both, those are different lock files = different instances (correct behavior).

### Stale-lock TTL

30 seconds. Set via `QLockFile.setStaleLockTime(30_000)`. If a previous process died without calling `release()` (kill -9, BSOD, power loss), the next launch within 30s sees the lock as held; after 30s the lock is considered stale and the new launch acquires it.

This means: after a crash, the user waits up to 30s before relaunching. Acceptable trade-off vs. the alternative of getting permanently locked out.

## Component contract

```python
class SingleInstanceLock:
    """QLockFile wrapper for single-instance enforcement.

    Usage:
        lock = SingleInstanceLock()
        if not lock.acquire():
            # show error, exit
            ...
        # ... app runs ...
        lock.release()  # or wire to QApplication.aboutToQuit
    """

    def __init__(self, lock_path: Optional[Path] = None):
        """lock_path defaults to <project_root>/data/.run_gui.lock.
        Override for tests."""

    def acquire(self) -> bool:
        """Try to acquire the lock with a 100ms wait. Returns True if
        held by this process, False if another process holds it."""

    def release(self) -> None:
        """Release the lock. Safe to call multiple times."""

    def is_held(self) -> bool:
        """For tests / debug. True if this instance currently holds."""
```

Internal state:
- `_lock_path: Path`
- `_qlock: Optional[QLockFile]` — lazy-created on first `acquire()` so tests can monkeypatch the path before construction
- `_held: bool` — local tracking flag

## Data flow

```
[Process A starts]
  └─ acquire() → tryLock(100) → True → _held=True
  └─ ... runs normally ...

[Process B starts while A is running]
  └─ acquire() → tryLock(100) → False
  └─ QMessageBox: "MTG Meta Analyzer is already running.\n\nCheck the
     system tray (bottom-right). Use Ctrl+Shift+Q in the existing
     window to force-quit if it's hung."
  └─ sys.exit(1)

[Process A exits via X button / tray Quit / Ctrl+Shift+Q]
  └─ QApplication.aboutToQuit → lock.release() → _held=False
  └─ Lock file removed

[Process B starts after A exited]
  └─ acquire() → tryLock(100) → True → _held=True (fresh)

[Process A killed via Task Manager / crash]
  └─ Lock file remains, _held flag in dead process irrelevant
  └─ Process B tries acquire() → tryLock(100) → False (within 30s of crash)
  └─ Process B tries acquire() 31s later → True (stale lock cleared)
```

## Error handling

| Scenario | Handling |
|---|---|
| `data/` directory missing | Create it (existing project pattern; `db.database` does this on connect) |
| Lock path unwritable (NTFS permissions) | `tryLock()` returns False with `QLockFile.PermissionError`. Treat as "blocked" — show user-friendly error mentioning the path. |
| QApplication not constructed before `acquire()` | Document at the call site: "QApplication must be instantiated first." Test enforces this. |
| `release()` called before `acquire()` | No-op; safe. |
| `release()` called multiple times | No-op; safe. |
| Lock file deleted manually mid-run | Process A still has the file handle from QLockFile's internal kept-open file descriptor; lock semantics persist for A. Next launch behaves as fresh. Not a real concern. |

## User-facing message

```
Title: MTG Meta Analyzer already running
Body:  Another instance is already running.

       Check the system tray (bottom-right corner of your taskbar) for
       the Team Resolve icon.

       If the existing window is unresponsive, use Ctrl+Shift+Q on it
       to force-quit, then wait 30 seconds before relaunching.

Button: OK
```

## Testing

`tests/test_single_instance.py`:

```python
def test_acquire_returns_true_on_first_call(tmp_path):
    """Fresh lock path: first acquire succeeds."""
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    assert lock.acquire() is True
    lock.release()


def test_acquire_returns_false_when_held(tmp_path):
    """Second instance against same path: acquire returns False."""
    path = tmp_path / ".test.lock"
    lock_a = SingleInstanceLock(lock_path=path)
    lock_b = SingleInstanceLock(lock_path=path)
    assert lock_a.acquire() is True
    assert lock_b.acquire() is False
    lock_a.release()


def test_release_allows_reacquire(tmp_path):
    """A.release() → A.acquire() again succeeds."""
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    assert lock.acquire() is True
    lock.release()
    assert lock.acquire() is True
    lock.release()


def test_release_is_idempotent(tmp_path):
    """release() can be called repeatedly without error."""
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    lock.acquire()
    lock.release()
    lock.release()  # no-op
    lock.release()  # no-op


def test_is_held_reflects_state(tmp_path):
    lock = SingleInstanceLock(lock_path=tmp_path / ".test.lock")
    assert lock.is_held() is False
    lock.acquire()
    assert lock.is_held() is True
    lock.release()
    assert lock.is_held() is False


def test_creates_parent_dir_if_missing(tmp_path):
    """Lock path with missing parent dir: should mkdir -p before locking."""
    nested = tmp_path / "deep" / "nested" / ".test.lock"
    lock = SingleInstanceLock(lock_path=nested)
    assert lock.acquire() is True
    assert nested.parent.exists()
    lock.release()
```

Skip QApplication-dependent tests; the lock itself is QApplication-independent (`QLockFile` doesn't require an event loop).

### Manual smoke

1. `python run_gui.py` — should launch normally.
2. In a second terminal, `python run_gui.py` again — should show the error dialog and exit with code 1.
3. Close first instance via X button.
4. Wait 1s, relaunch — should succeed.
5. **Crash test:** Force-kill the first instance via `Stop-Process -Force` (don't run the cleanup hook).
6. Immediately try to relaunch — should still see the dialog (lock is held).
7. Wait 31 seconds, try again — should succeed (stale lock cleared).

## File structure

**Create:**
- `gui/single_instance.py` — `SingleInstanceLock` class (~60 lines)
- `tests/test_single_instance.py` — 6 tests (~50 lines)

**Modify:**
- `run_gui.py` — add ~12 lines: import, instantiate lock right after QApplication, acquire-or-exit, wire release to aboutToQuit
- `CLAUDE.md` — add single-instance line under "Critical Implementation Notes"
- `NEXT_STEPS.md` — strike-through the existing single-instance enforcement bullet under "Tomorrow's chain"

## Trade-offs accepted

1. **No "focus existing window" UX.** Second launch closes cleanly with a dialog; user alt-tabs manually. Future enhancement via QLocalSocket if it ever feels worth the complexity.
2. **30s stale-lock wait after a crash.** Beats the alternative of permanent lockout.
3. **One lock per project-root path.** Multiple clones run independently. Correct for dev workflow but documented as a quirk.

## Out of scope

- Crash-recovery state restore (different problem; separate spec).
- Health monitoring panel (covered in the alternative scope option, deferred).
- Endurance test automation (manual checklist task, not code).

---

**End of spec.**
