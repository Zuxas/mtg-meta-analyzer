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
