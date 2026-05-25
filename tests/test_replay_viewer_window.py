"""Offscreen-Qt smoke tests for gui/widgets/replay_viewer_window.py."""
import pytest


@pytest.fixture(autouse=True)
def _offscreen_qt(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Stub the Scryfall image fetch so window tests never hit the network
    # (load_pixmap otherwise blocks up to 8s on a cache miss). The viewer
    # falls back to rendering the card name as text when this returns None.
    monkeypatch.setattr(
        "gui.widgets.card_image_cache.load_pixmap",
        lambda **kwargs: None,
    )


def _sample_stream():
    """Minimal but realistic build_event_stream() output: 1 game, 2 turns,
    a phase with a step and a phase without, a cast + counter + life + end."""
    def ev(seq, **kw):
        base = {
            "seq": seq, "game_num": 1, "turn_num": 1, "phase": "Phase_Main1",
            "step": None, "active_seat": 1, "priority_seat": 1, "actor_seat": 1,
            "kind": "cast_spell", "card_name": None, "card_grpid": None,
            "targets": [], "details": {}, "life_after": {"you": 20, "opp": 20},
            "mana_pool_after": {"you": "", "opp": ""}, "stack_after": [],
            "board_diff": [], "log_offset": None, "revealed_cards": [],
            "shuffle_cause": None,
        }
        base.update(kw)
        return base
    events = [
        ev(0, kind="phase_change", phase="Phase_Beginning", step="Step_Upkeep"),
        ev(1, kind="draw_card", phase="Phase_Beginning", step="Step_Draw",
           card_name="Island"),
        ev(2, kind="phase_change", phase="Phase_Main1", step=None),
        ev(3, kind="cast_spell", phase="Phase_Main1", card_name="Lightning Strike",
           card_grpid=70404,
           targets=[{"name": "Make Disappear", "grpid": 81234, "kind": "spell"}],
           stack_after=[{"name": "Lightning Strike", "controller": "you", "targets": []}]),
        ev(4, kind="counter_spell", phase="Phase_Main1", actor_seat=2,
           card_name="Make Disappear"),
        ev(5, kind="life_change", turn_num=2, phase="Phase_Combat",
           step="Step_CombatDamage", details={"seat": 2, "delta": -3, "from": 20, "to": 17},
           life_after={"you": 20, "opp": 17}),
        ev(6, kind="game_end", turn_num=2, details={"reason": "Concede", "winning_seat": 1}),
    ]
    return {
        "arena_match_id": "test-match", "schema_version": 1,
        "capabilities": {"events": True}, "my_seat": 1, "opp_seat": 2,
        "opp_name": "Bob",
        "match_meta": {
            "event_name": "Constructed_BestOf3_Ranked", "winner_seat": 1,
            "winner_reason": "Concede",
            "key_events_by_turn": [
                {"turn": 1, "kind": "first_spell", "actor": "you", "seq": 3,
                 "card": "Lightning Strike"},
                {"turn": 2, "kind": "concede", "actor": "opp", "seq": 6},
            ],
            "games": [],
        },
        "events": events,
    }


def test_table_model_rows_and_cells():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayEventTableModel
    s = _sample_stream()
    model = ReplayEventTableModel(s["events"], [e["seq"] for e in s["events"]],
                                  my_seat=1, opp_seat=2, opp_name="Bob")
    assert model.rowCount() == 7
    assert model.columnCount() == 4
    # Row 3 = the cast
    idx = model.index(3, 3)  # Event column
    assert "Lightning Strike" in model.data(idx, Qt.ItemDataRole.DisplayRole)
    # seq <-> row mapping
    assert model.seq_for_row(3) == 3
    assert model.row_for_seq(3) == 3


def test_table_model_visible_subset():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayEventTableModel
    s = _sample_stream()
    model = ReplayEventTableModel(s["events"], [3, 4], my_seat=1, opp_seat=2,
                                  opp_name="Bob")
    assert model.rowCount() == 2
    assert model.seq_for_row(0) == 3
    assert model.row_for_seq(4) == 1
    assert model.row_for_seq(0) is None  # seq 0 not visible
    # Reset to a different subset
    model.set_visible_seqs([0, 1, 2, 3, 4, 5, 6])
    assert model.rowCount() == 7


def test_window_constructs_and_populates():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", opp_name="Bob",
                           defer_load=True)
    # No data yet -> table model empty / None
    w._on_data_ready(_sample_stream())
    assert w._model is not None
    assert w._model.rowCount() == 7
    # Current selection defaults to first event
    assert w._current_seq == 0
    # Title carries the match id
    assert "test-match" in w.windowTitle()


def test_window_select_seq_updates_current():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)
    assert w._current_seq == 3


def test_window_handles_none_stream():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="missing", defer_load=True)
    w._on_data_ready(None)  # match not in log
    assert w._model is None or w._model.rowCount() == 0


def test_open_full_viewer_helper_returns_window():
    """deck_match_history.open_full_replay_viewer builds a ReplayViewerWindow."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.deck_match_history import open_full_replay_viewer
    w = open_full_replay_viewer(
        arena_match_id="test-match", opp_name="Bob", my_deck_label="Izzet",
        parent=None, defer_load=True,
    )
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    assert isinstance(w, ReplayViewerWindow)
    assert w._arena_match_id == "test-match"


def test_window_kind_filter_rebuilds_visible():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    # Turn OFF everything except "Casts" -> only cast_spell (seq 3) + play_land remain.
    w._active_groups = {"Casts"}
    w._apply_kind_filter()
    visible = [w._model.seq_for_row(r) for r in range(w._model.rowCount())]
    assert 3 in visible          # the cast
    assert 5 not in visible      # life_change filtered out


def test_window_nav_buttons_move_cursor():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(0)
    w._on_nav("next")
    assert w._current_seq == 1
    w._on_nav("last")
    assert w._current_seq == 6
    w._on_nav("first")
    assert w._current_seq == 0


def test_window_search_filters_proxy():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._on_search_changed("Lightning")
    # Proxy now shows only rows whose Event text contains "Lightning"
    assert w._proxy.rowCount() == 1
    w._on_search_changed("")
    assert w._proxy.rowCount() == w._model.rowCount()


def test_window_nav_respects_search_filter():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._on_search_changed("Lightning")   # only the cast (seq 3) matches
    assert w._proxy.rowCount() == 1
    w._select_seq(3)
    w._on_nav("next")                    # nothing else visible -> clamp to 3
    assert w._current_seq == 3
    assert w._table.selectionModel().hasSelection()


def test_window_all_chips_off_clears_counter():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._active_groups = set()             # uncheck everything
    w._apply_kind_filter()
    assert w._model.rowCount() == 0
    assert "0" in w._counter_lbl.text()
    assert w._current_seq is None


def test_window_tree_populates_and_selects():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    # Tree has at least one game root
    assert w._tree.topLevelItemCount() >= 1
    # Find an event leaf carrying seq 3 and activate it
    leaf = w._find_tree_leaf(3)
    assert leaf is not None
    w._on_tree_item_clicked(leaf, 0)
    assert w._current_seq == 3


def test_window_detail_pane_updates_on_select():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)  # the Lightning Strike cast
    txt = w._detail_text()
    assert "Lightning Strike" in txt
    assert w._stack_list.count() == 1
    assert w._always_lbl.text()


def test_window_jump_menu_built():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    assert len(w._jump_btn.menu().actions()) == 2


def test_window_board_panel_renders_on_select():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from gui.widgets.replay_board_panel import ReplayBoardPanel
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    assert isinstance(w._board_panel, ReplayBoardPanel)
    w._select_seq(3)   # the Lightning Strike cast
    assert "20" in w._board_panel._header_text("you")   # sample life is 20/20


def test_window_show_board_changes_toggle_rerenders():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)
    w._show_board_changes.setChecked(True)
    assert w._show_board_changes.isChecked()


def test_window_select_expands_tree_ancestors():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    leaf = w._find_tree_leaf(1)  # a draw under Beginning/Draw (nested under game/turn)
    assert leaf is not None
    # collapse all ancestors first
    p = leaf.parent()
    while p is not None:
        p.setExpanded(False)
        p = p.parent()
    w._select_seq(1)
    # after selecting, the leaf's immediate parent must be expanded (revealed)
    assert leaf.parent().isExpanded()


def test_window_kind_filter_keeps_surviving_selection_synced():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)               # the cast (Casts group) -- survives the filter below
    w._active_groups = {"Casts"}   # only seq 3 remains visible
    w._apply_kind_filter()
    # The surviving selection stays current AND the table highlight is restored.
    assert w._current_seq == 3
    assert w._table.selectionModel().hasSelection()
    # Counter reflects seq 3's NEW position in the filtered set (row 0 -> "Event 1/...").
    row = w._model.row_for_seq(3)
    assert f"{row + 1}/" in w._counter_lbl.text()


def test_window_reload_rerenders_board():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="test-match", defer_load=True)
    w._on_data_ready(_sample_stream())     # initial load renders the board once
    # Spy on the panel's render so we can prove the reload re-renders.
    calls = []
    orig = w._board_panel.render
    w._board_panel.render = lambda *a, **k: calls.append(1) or orig(*a, **k)
    w._on_data_ready(_sample_stream())     # reload the same match
    assert calls, "board must re-render on reload (memo must be reset, not stale)"


def test_window_notes_load_and_save(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from db.match_log import get_replay_notes
    w = ReplayViewerWindow(arena_match_id="arena-note", defer_load=True)
    w._on_data_ready(_sample_stream())
    assert not w._notes.isReadOnly()                 # editable now
    w._notes.setPlainText("held up burn on T7")
    w._persist_replay_notes(flash=True)
    assert get_replay_notes("arena-note")["text"] == "held up burn on T7"
    # A fresh window for the same match loads the saved notes.
    w2 = ReplayViewerWindow(arena_match_id="arena-note", defer_load=True)
    w2._on_data_ready(_sample_stream())
    assert w2._notes.toPlainText() == "held up burn on T7"


def test_window_closeevent_persists_notes(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QCloseEvent
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from db.match_log import get_replay_notes
    w = ReplayViewerWindow(arena_match_id="arena-close", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._notes.setPlainText("typed then closed")
    w.closeEvent(QCloseEvent())                      # read text -> DB -> base
    assert get_replay_notes("arena-close")["text"] == "typed then closed"


def test_window_mark_toggle_persists_and_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from db.match_log import get_replay_notes
    w = ReplayViewerWindow(arena_match_id="arena-mark", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)
    w._toggle_mark()
    assert 3 in w._marked_seqs
    assert "Marked" in w._mark_btn.text()                 # ★ Marked
    assert get_replay_notes("arena-mark")["marks"] == [3] # persisted
    assert len(w._jump_btn.menu().actions()) >= 1
    w._toggle_mark()
    assert 3 not in w._marked_seqs
    assert get_replay_notes("arena-mark")["marks"] == []


def test_window_mark_button_disabled_when_no_visible_event(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="arena-mark2", defer_load=True)
    assert not w._mark_btn.isEnabled()      # before any data/selection


def test_window_build_review_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="arena-export", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._notes.setPlainText("kept the counter up")
    w._select_seq(3)
    w._toggle_mark()                       # mark the cast
    md = w._build_review_markdown()
    assert "# Replay review" in md
    assert "kept the counter up" in md
    assert "## Marked events" in md
    assert "Lightning Strike" in md        # the marked event from _sample_stream


def test_window_export_btn_enabled_only_after_load():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="arena-x", defer_load=True)
    assert not w._export_btn.isEnabled()       # disabled before data
    w._on_data_ready(_sample_stream())
    assert w._export_btn.isEnabled()           # enabled once a replay loads


def test_window_mark_button_disabled_when_all_events_filtered():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    w = ReplayViewerWindow(arena_match_id="arena-y", defer_load=True)
    w._on_data_ready(_sample_stream())
    w._select_seq(3)
    w._active_groups = set()                   # uncheck everything -> 0 visible
    w._apply_kind_filter()
    assert w._model.rowCount() == 0
    assert not w._mark_btn.isEnabled()         # Mark disabled when nothing visible


def test_window_match_not_found_does_not_wipe_notes(tmp_path, monkeypatch):
    monkeypatch.setattr("db.database.DB_PATH", tmp_path / "m.db")
    monkeypatch.setattr("db.database.ARCHIVE_PATH", tmp_path / "m_arc.db")
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QCloseEvent
    app = QApplication.instance() or QApplication([])
    from gui.widgets.replay_viewer_window import ReplayViewerWindow
    from db.match_log import save_replay_notes, get_replay_notes
    # Notes exist from an earlier view (when the log was fresh).
    save_replay_notes("arena-rot", "important review note", [3])
    w = ReplayViewerWindow(arena_match_id="arena-rot", defer_load=True)
    w._on_data_ready(None)               # match not found / log rotated -> no load
    w.closeEvent(QCloseEvent())          # must NOT clobber the stored note
    assert get_replay_notes("arena-rot")["text"] == "important review note"
    assert get_replay_notes("arena-rot")["marks"] == [3]
