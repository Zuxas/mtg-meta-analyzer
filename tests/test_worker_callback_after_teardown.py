"""Worker result callbacks must not explode when their widgets are gone.

A DataLoadWorker finishes on a background thread and delivers its result via
a queued Qt signal. That delivery can land AFTER the tab it belongs to has
been torn down -- fast tab switching, app exit, or a test calling cleanup()
while a load is still in flight. Touching a widget whose C++ side is already
destroyed raises

    RuntimeError: wrapped C/C++ object of type QComboBox has been deleted

out of a Qt callback, where nothing catches it.

Found empirically: a probe harness constructing every tab against a fresh
database died at gui/tabs/event_optimizer.py:316,
`_refresh_deck_combo._done` doing self._deck_combo.blockSignals(True) after
the tab had been cleaned up. All six _done callbacks in that module had the
same exposure, so the guard is applied to all six rather than only the one
that happened to be tripped.

The guard is NARROW on purpose: only the "has been deleted" RuntimeError is
dropped. A genuine RuntimeError raised by the callback body must still
surface, which the second test pins -- swallowing those would hide real bugs
behind a teardown excuse.
"""
import pytest

from gui.tabs.event_optimizer import _skip_if_widgets_deleted


def test_deleted_widget_runtimeerror_is_dropped():
    """The exact Qt teardown error is swallowed and the callback returns None."""
    calls = []

    @_skip_if_widgets_deleted
    def _done(payload):
        calls.append(payload)
        raise RuntimeError(
            "wrapped C/C++ object of type QComboBox has been deleted"
        )

    assert _done(["a deck"]) is None      # must not propagate
    assert calls == [["a deck"]]          # body really did run


def test_unrelated_runtimeerror_still_propagates():
    """A real RuntimeError from the callback body is NOT masked."""

    @_skip_if_widgets_deleted
    def _done(payload):
        raise RuntimeError("dictionary changed size during iteration")

    with pytest.raises(RuntimeError, match="dictionary changed size"):
        _done([])


def test_non_runtime_exceptions_still_propagate():
    """Only RuntimeError is considered; other bugs surface untouched."""

    @_skip_if_widgets_deleted
    def _done(payload):
        return payload["missing"]

    with pytest.raises(TypeError):
        _done(None)


def test_result_passes_through_untouched_on_the_happy_path():
    """The guard must be transparent when nothing has been deleted."""

    @_skip_if_widgets_deleted
    def _done(payload):
        return {"seen": payload}

    assert _done(42) == {"seen": 42}


def test_every_done_callback_in_event_optimizer_is_guarded():
    """Pins the "all six, not just the one that crashed" decision.

    If a new worker callback is added without the decorator it reopens the
    same crash, so the count is asserted against the source directly.
    """
    import inspect

    import gui.tabs.event_optimizer as mod

    src = inspect.getsource(mod)
    done_defs = src.count("        def _done(")
    guarded = src.count("        @_skip_if_widgets_deleted\n        def _done(")
    assert done_defs > 0, "no _done callbacks found -- test needs updating"
    assert guarded == done_defs, (
        f"{done_defs - guarded} of {done_defs} _done callbacks in "
        "event_optimizer.py are missing @_skip_if_widgets_deleted"
    )
