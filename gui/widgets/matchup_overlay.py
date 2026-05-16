"""Transparent frameless overlay with SB plan + matchup notes for the
currently-active MTGA match. Always on top.

Locked mode (default ON):
  - Click-through: clicks pass to MTGA underneath
  - Overlay is visible but doesn't interfere with play
  - Ctrl+Shift+L toggles to Unlocked

Unlocked mode:
  - Overlay receives mouse events
  - Drag anywhere on the card body to reposition

Reads latest match_log row with source='mtga_log' to determine
(my_deck_id, opp_archetype). Auto-refreshes via
MtgaLogWatcher.matches_imported signal AND via the in-overlay ↻ button.
"""
from __future__ import annotations

import json
from collections import Counter

from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QSlider, QComboBox,
)

import gui.theme as theme


class MatchupOverlay(QWidget):
    """Transparent always-on-top SB plan card."""

    # State change signals (MainWindow uses these to persist to ui_state)
    compact_changed = pyqtSignal(bool)
    notes_open_changed = pyqtSignal(bool)
    decklist_open_changed = pyqtSignal(bool)
    opacity_changed = pyqtSignal(float)
    # Empty string => "Auto" (follow latest match)
    opp_override_changed = pyqtSignal(str)
    # 0 => "Auto" (follow latest match)
    deck_override_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setWindowFlags(
            self._base_flags | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self._locked = True
        # Remember the lock state we had before entering compact so it
        # can be restored on expand. Compact forces clicks-receivable.
        self._pre_compact_locked: bool | None = None
        self._drag_pos = None
        self._compact = False
        # Manual matchup override (None = follow latest match)
        self._opp_override: str | None = None
        # Manual deck override (None = follow latest match / fallback)
        self._deck_override: int | None = None
        # Cached effective deck id so the decklist panel reads the same
        # deck refresh() picked (override / fallback aware).
        self._effective_deck_id: int | None = None
        # Track full-mode size + position so we can restore from compact
        self._full_size: tuple[int, int] = (380, 540)
        self._full_geom: tuple[int, int, int, int] | None = None
        self.setMinimumSize(180, 40)
        self.resize(*self._full_size)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(0)

        self.setStyleSheet(
            f"QLabel {{ background: transparent; color: {theme.TEXT}; }} "
            "QWidget#overlayCard { "
            "background: rgba(20, 24, 36, 220); "
            f"border: 2px solid {theme.ACCENT}; "
            "border-radius: 6px; } "
            "QPushButton#overlayRefresh { "
            f"background: transparent; color: {theme.ACCENT}; "
            f"border: 1px solid {theme.BORDER}; border-radius: 3px; "
            "padding: 2px 6px; font-size: 11px; } "
            "QPushButton#overlayRefresh:hover { "
            f"border-color: {theme.ACCENT}; }} "
            "QTextEdit#overlayNotes { "
            "background: rgba(15, 18, 28, 220); "
            f"color: {theme.TEXT}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 6px; "
            f"font-family: '{theme.BODY_FONT}', Arial, sans-serif; "
            "font-size: 10px; }"
        )

        self._card = QWidget()
        self._card.setObjectName("overlayCard")
        cv = QVBoxLayout(self._card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(6)

        # Header row: title + notes toggle + refresh button
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)
        self._header = QLabel("<b>Matchup overlay</b>")
        self._header.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 13px;"
        )
        header_row.addWidget(self._header, 1)
        self._compact_btn = QPushButton("−")
        self._compact_btn.setObjectName("overlayRefresh")
        self._compact_btn.setToolTip(
            "Compact: collapse to a thin pill. Click again to expand."
        )
        self._compact_btn.setFixedWidth(28)
        self._compact_btn.setCheckable(True)
        self._compact_btn.toggled.connect(self._on_compact_toggle)
        header_row.addWidget(self._compact_btn)
        self._decklist_toggle_btn = QPushButton("📋")
        self._decklist_toggle_btn.setObjectName("overlayRefresh")
        self._decklist_toggle_btn.setToolTip(
            "Show / hide your saved decklist (main + sideboard). "
            "MTGA hides your own list during a match -- this is your cheat sheet."
        )
        self._decklist_toggle_btn.setFixedWidth(28)
        self._decklist_toggle_btn.setCheckable(True)
        self._decklist_toggle_btn.setChecked(False)  # default: hidden
        self._decklist_toggle_btn.toggled.connect(self._on_decklist_toggle)
        header_row.addWidget(self._decklist_toggle_btn)
        self._notes_toggle_btn = QPushButton("≡")
        self._notes_toggle_btn.setObjectName("overlayRefresh")
        self._notes_toggle_btn.setToolTip(
            "Show / hide the matchup notes panel."
        )
        self._notes_toggle_btn.setFixedWidth(28)
        self._notes_toggle_btn.setCheckable(True)
        self._notes_toggle_btn.setChecked(True)  # default: notes visible
        self._notes_toggle_btn.toggled.connect(self._on_notes_toggle)
        header_row.addWidget(self._notes_toggle_btn)
        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("overlayRefresh")
        self._refresh_btn.setToolTip(
            "Refresh from latest match (also auto-refreshes within 30s of "
            "match end)."
        )
        self._refresh_btn.setFixedWidth(28)
        self._refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(self._refresh_btn)
        cv.addLayout(header_row)

        # Subheader: vs opp_name etc.
        self._subheader = QLabel("Waiting for first MTGA match…")
        self._subheader.setTextFormat(Qt.TextFormat.RichText)
        self._subheader.setWordWrap(True)
        cv.addWidget(self._subheader)

        # Deck override dropdown (which saved deck's plans to show)
        deck_row = QHBoxLayout()
        deck_row.setContentsMargins(0, 2, 0, 0)
        deck_row.setSpacing(6)
        deck_lbl = QLabel("deck")
        deck_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 9px;"
        )
        deck_row.addWidget(deck_lbl)
        self._deck_combo = QComboBox()
        combo_style = (
            "QComboBox { background: rgba(15, 18, 28, 220); "
            f"color: {theme.TEXT}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 1px 4px; font-size: 10px; }"
        )
        self._deck_combo.setStyleSheet(combo_style)
        self._deck_combo.setMinimumWidth(180)
        self._deck_combo.addItem("Auto (latest match)", 0)
        self._deck_combo.currentIndexChanged.connect(
            self._on_deck_combo_changed
        )
        deck_row.addWidget(self._deck_combo, 1)
        self._deck_widget = QWidget()
        self._deck_widget.setLayout(deck_row)
        cv.addWidget(self._deck_widget)

        # Matchup override dropdown ("Auto" + saved plans for the deck)
        opp_row = QHBoxLayout()
        opp_row.setContentsMargins(0, 2, 0, 0)
        opp_row.setSpacing(6)
        opp_lbl = QLabel("matchup")
        opp_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 9px;"
        )
        opp_row.addWidget(opp_lbl)
        self._opp_combo = QComboBox()
        self._opp_combo.setStyleSheet(combo_style)
        self._opp_combo.setMinimumWidth(180)
        self._opp_combo.addItem("Auto (latest match)", "")
        self._opp_combo.currentIndexChanged.connect(self._on_opp_combo_changed)
        opp_row.addWidget(self._opp_combo, 1)
        opp_widget = QWidget()
        opp_widget.setLayout(opp_row)
        self._opp_widget = opp_widget
        cv.addWidget(opp_widget)

        # Record vs this archetype (last 10 matches, W-L + per-game)
        self._record = QLabel("")
        self._record.setTextFormat(Qt.TextFormat.RichText)
        self._record.setWordWrap(True)
        self._record.setVisible(False)
        cv.addWidget(self._record)

        # Cards opp tends to play (aggregated grpIds across prior matches)
        self._opp_cards = QLabel("")
        self._opp_cards.setTextFormat(Qt.TextFormat.RichText)
        self._opp_cards.setWordWrap(True)
        self._opp_cards.setVisible(False)
        cv.addWidget(self._opp_cards)

        # IN/OUT plan (compact, always visible)
        self._plan = QLabel("")
        self._plan.setTextFormat(Qt.TextFormat.RichText)
        self._plan.setWordWrap(True)
        self._plan.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        cv.addWidget(self._plan)

        # Notes (scrollable; only takes space if there's content)
        self._notes = QTextEdit()
        self._notes.setObjectName("overlayNotes")
        self._notes.setReadOnly(True)
        self._notes.setVisible(False)
        cv.addWidget(self._notes, 1)

        # My decklist quick reference (scrollable)
        self._decklist = QTextEdit()
        self._decklist.setObjectName("overlayNotes")
        self._decklist.setReadOnly(True)
        self._decklist.setVisible(False)
        cv.addWidget(self._decklist, 1)

        # Opacity slider (acts on the whole widget; 0.30 - 1.00)
        opacity_row = QHBoxLayout()
        opacity_row.setContentsMargins(0, 4, 0, 0)
        opacity_row.setSpacing(6)
        opacity_lbl = QLabel("opacity")
        opacity_lbl.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 9px;"
        )
        opacity_row.addWidget(opacity_lbl)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setMinimum(30)
        self._opacity_slider.setMaximum(100)
        self._opacity_slider.setValue(95)
        self._opacity_slider.setFixedHeight(14)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_row.addWidget(self._opacity_slider, 1)
        self._opacity_lbl_value = QLabel("95%")
        self._opacity_lbl_value.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 9px;"
        )
        self._opacity_lbl_value.setFixedWidth(36)
        opacity_row.addWidget(self._opacity_lbl_value)
        opacity_widget = QWidget()
        opacity_widget.setLayout(opacity_row)
        self._opacity_widget = opacity_widget
        cv.addWidget(opacity_widget)

        # Footer with lock state + hotkey hints
        self._footer = QLabel("")
        self._footer.setTextFormat(Qt.TextFormat.RichText)
        cv.addWidget(self._footer)

        v.addWidget(self._card)
        self._update_footer()

        # Mouse events from the inner card need to forward to self so
        # drag works anywhere on the body, not just on the 8px outer
        # transparent margin.
        self._card.installEventFilter(self)

    def _on_compact_toggle(self, checked: bool) -> None:
        """Hide all body widgets so only the header pill remains.

        On compact, shrink to a thin vertical pip (90x200) at the right
        edge of the screen so it tucks under MTGA's play button area.
        Click anywhere on the compact pip to expand again.

        Critical: Qt's layout system enforces a minimum size based on
        child widgets even when they're hidden, so we must clamp both
        minimumSize AND maximumSize to force the requested compact size.
        """
        self._compact = checked
        for w in (self._subheader, self._deck_widget, self._opp_widget,
                  self._record, self._opp_cards, self._plan, self._notes,
                  self._decklist, self._opacity_widget, self._footer):
            w.setVisible(not checked)
        # In compact mode, swap the header text to a vertical-friendly
        # short label and hide the right-side buttons except compact (+).
        for btn in (self._decklist_toggle_btn, self._notes_toggle_btn,
                    self._refresh_btn):
            btn.setVisible(not checked)
        if not checked:
            # Restore lock state from before we compacted
            if self._pre_compact_locked is not None:
                self.set_locked(self._pre_compact_locked)
                self._pre_compact_locked = None
            # Release size clamps so the window can grow back
            self.setMinimumSize(180, 40)
            self.setMaximumSize(16777215, 16777215)
            self._header.setText("<b>Matchup overlay</b>")
            self._header.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: 13px;"
            )
            from PyQt6.QtCore import QRect
            r = self._full_geom
            if r is not None:
                self.setGeometry(QRect(*r))
            else:
                self.resize(*self._full_size)
            self._compact_btn.setText("−")
            # Re-run the data-dependent visibility logic so notes /
            # record / opp_cards reappear if they had content.
            self.refresh()
        else:
            # Force unlocked while compact so the user can click the pip
            # to expand. Save prior state for restore on expand.
            self._pre_compact_locked = self._locked
            if self._locked:
                self.set_locked(False)
            # Stash current geometry, shrink to a small horizontal pip
            # in the bottom-right of the screen.
            g = self.geometry()
            self._full_geom = (g.x(), g.y(), g.width(), g.height())
            self._full_size = (g.width(), g.height())
            pip_w, pip_h = 240, 44
            from PyQt6.QtWidgets import QApplication
            screen = (
                self.screen() if hasattr(self, "screen") else None
            ) or QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                target_x = avail.right() - pip_w - 12
                target_y = avail.bottom() - pip_h - 12
            else:
                target_x, target_y = g.x(), g.y()
            # Use the latest match data for the pip label
            self._update_compact_label()
            self.setMinimumSize(pip_w, pip_h)
            self.setMaximumSize(pip_w, pip_h)
            self.setGeometry(target_x, target_y, pip_w, pip_h)
            self._compact_btn.setText("+")
        self.compact_changed.emit(checked)

    def _update_compact_label(self) -> None:
        """Single-line horizontal pip label: 'deck vs opp · click to expand'."""
        full = self._subheader.text() or ""
        import re
        deck_match = re.search(r"<b[^>]*>([^<]+)</b>", full)
        deck = (deck_match.group(1) if deck_match else "?").strip()
        # First two words of deck name for a compact but recognizable label
        short_deck = " ".join(deck.split()[:2]) if deck else "?"
        if len(short_deck) > 14:
            short_deck = short_deck[:14]
        opp_match = re.search(r"vs\s*<b>([^<]+)</b>", full)
        opp = (opp_match.group(1) if opp_match else "?").strip()
        short_opp = " ".join(opp.split()[:2]) if opp else "?"
        if len(short_opp) > 14:
            short_opp = short_opp[:14]
        self._header.setText(
            f"<span style='color:{theme.ACCENT};font-weight:bold;'>"
            f"{short_deck}</span> "
            f"<span style='color:{theme.TEXT_DIM};'>vs</span> "
            f"<span style='color:{theme.TEXT};font-weight:bold;'>"
            f"{short_opp}</span> "
            f"<span style='color:{theme.TEXT_DIM};font-size:9px;'>"
            f"&middot; click to expand</span>"
        )
        self._header.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 11px; padding: 2px 6px;"
        )

    def set_compact(self, compact: bool) -> None:
        """Programmatic toggle (does not echo a signal back via the button)."""
        if self._compact_btn.isChecked() != compact:
            self._compact_btn.setChecked(compact)

    def _on_notes_toggle(self, checked: bool) -> None:
        # Always respect the button. When there's no canonical plan or
        # the plan has empty notes, the panel will render a placeholder
        # set by refresh() -- so the toggle always produces visible
        # feedback.
        if checked and not (self._notes.toPlainText() or "").strip():
            # Lazy placeholder if refresh hasn't populated yet
            self._notes.setHtml(
                f"<i style='color:{theme.TEXT_DIM};'>"
                "No notes for the current matchup.</i>"
            )
        self._notes.setVisible(checked)
        self.notes_open_changed.emit(checked)

    def set_notes_open(self, open_: bool) -> None:
        """Programmatic toggle."""
        if self._notes_toggle_btn.isChecked() != open_:
            self._notes_toggle_btn.setChecked(open_)

    def _on_decklist_toggle(self, checked: bool) -> None:
        # Refresh the decklist content so we have the latest snapshot
        if checked:
            self._render_decklist()
        self._decklist.setVisible(checked)
        self.decklist_open_changed.emit(checked)

    def set_decklist_open(self, open_: bool) -> None:
        if self._decklist_toggle_btn.isChecked() != open_:
            self._decklist_toggle_btn.setChecked(open_)

    def _sync_deck_combo(self, decks: list[tuple[int, str]]) -> None:
        """Rebuild the deck dropdown. decks is [(id, name), ...]."""
        current_id = self._deck_combo.currentData() or 0
        blocker = self._deck_combo.blockSignals(True)
        try:
            self._deck_combo.clear()
            self._deck_combo.addItem("Auto (latest match)", 0)
            for did, name in decks:
                self._deck_combo.addItem(name, did)
            idx = 0
            for i in range(self._deck_combo.count()):
                if self._deck_combo.itemData(i) == current_id:
                    idx = i
                    break
            self._deck_combo.setCurrentIndex(idx)
        finally:
            self._deck_combo.blockSignals(blocker)

    def _on_deck_combo_changed(self, _index: int) -> None:
        did = int(self._deck_combo.currentData() or 0)
        self._deck_override = did if did > 0 else None
        # Clear matchup override when deck changes -- different deck has
        # a different plan namespace.
        if self._opp_override:
            self._opp_override = None
            blocker = self._opp_combo.blockSignals(True)
            try:
                self._opp_combo.setCurrentIndex(0)
            finally:
                self._opp_combo.blockSignals(blocker)
            self.opp_override_changed.emit("")
        self.deck_override_changed.emit(did)
        self.refresh()

    def set_deck_override(self, deck_id: int) -> None:
        target = int(deck_id or 0)
        idx = 0
        for i in range(self._deck_combo.count()):
            if (self._deck_combo.itemData(i) or 0) == target:
                idx = i
                break
        if self._deck_combo.currentIndex() != idx:
            self._deck_combo.setCurrentIndex(idx)

    def _sync_opp_combo(self, archetypes: list[str]) -> None:
        """Rebuild the opp dropdown if its contents are out of sync."""
        current_data = self._opp_combo.currentData() or ""
        # Block signals during repopulation so we don't fire a self-refresh
        blocker = self._opp_combo.blockSignals(True)
        try:
            self._opp_combo.clear()
            self._opp_combo.addItem("Auto (latest match)", "")
            for a in archetypes:
                self._opp_combo.addItem(a, a)
            # Restore prior selection if still present
            idx = 0
            for i in range(self._opp_combo.count()):
                if (self._opp_combo.itemData(i) or "") == current_data:
                    idx = i
                    break
            self._opp_combo.setCurrentIndex(idx)
        finally:
            self._opp_combo.blockSignals(blocker)

    def _on_opp_combo_changed(self, _index: int) -> None:
        data = self._opp_combo.currentData()
        self._opp_override = (data or None)
        self.opp_override_changed.emit(data or "")
        self.refresh()

    def set_opp_override(self, archetype: str) -> None:
        """Programmatic override. Empty string => Auto."""
        target = archetype or ""
        # Find matching index; default to 0 (Auto) if not found
        idx = 0
        for i in range(self._opp_combo.count()):
            if (self._opp_combo.itemData(i) or "") == target:
                idx = i
                break
        if self._opp_combo.currentIndex() != idx:
            self._opp_combo.setCurrentIndex(idx)

    def _on_opacity_changed(self, value: int) -> None:
        opacity = max(0.30, min(1.00, value / 100.0))
        self.setWindowOpacity(opacity)
        self._opacity_lbl_value.setText(f"{value}%")
        self.opacity_changed.emit(opacity)

    def set_opacity(self, opacity: float) -> None:
        """Programmatic setter. Clamps to [0.30, 1.00]."""
        clamped = max(0.30, min(1.00, opacity))
        pct = int(round(clamped * 100))
        if self._opacity_slider.value() != pct:
            self._opacity_slider.setValue(pct)

    def _render_decklist(self) -> None:
        """Render mainboard + sideboard for the EFFECTIVE deck -- same one
        the rest of the overlay is using (manual override / fallback)."""
        from db.saved_decks import get_decks
        # Use the deck that refresh() picked. If refresh hasn't run yet
        # (toggle clicked before first refresh), trigger one to populate.
        if self._effective_deck_id is None:
            self.refresh()
        deck_id = self._effective_deck_id
        if deck_id is None:
            self._decklist.setHtml(
                f"<i style='color:{theme.TEXT_DIM};'>No saved deck "
                "available.</i>"
            )
            return
        try:
            deck = next(
                (d for d in get_decks() if d.get("id") == deck_id),
                None,
            )
        except Exception as exc:
            self._decklist.setHtml(
                f"<span style='color:#f04040;'>Decklist query failed: "
                f"{exc}</span>"
            )
            return

        if deck is None:
            self._decklist.setHtml(
                f"<i style='color:{theme.TEXT_DIM};'>"
                "Saved deck not found.</i>"
            )
            return
        # get_decks() deserializes mainboard/sideboard to dicts, but
        # tolerate raw JSON strings too in case a different code path
        # leaks one through.
        main = deck.get("mainboard") or {}
        if isinstance(main, str):
            try:
                main = json.loads(main)
            except Exception:
                main = {}
        if not isinstance(main, dict):
            main = {}
        side = deck.get("sideboard") or {}
        if isinstance(side, str):
            try:
                side = json.loads(side)
            except Exception:
                side = {}
        if not isinstance(side, dict):
            side = {}

        parts = [
            f"<div style='color:{theme.ACCENT};font-weight:bold;"
            f"margin-bottom:2px;'>{deck.get('name','?')} &mdash; main "
            f"({sum(main.values())})</div>"
        ]
        for name in sorted(main.keys()):
            q = main[name]
            parts.append(f"&nbsp;{q} {name}")
        parts.append(
            f"<br/><div style='color:{theme.ACCENT};font-weight:bold;"
            f"margin-top:6px;margin-bottom:2px;'>Sideboard "
            f"({sum(side.values())})</div>"
        )
        for name in sorted(side.keys()):
            q = side[name]
            parts.append(f"&nbsp;{q} {name}")
        self._decklist.setHtml("<br/>".join(parts))

    def _update_footer(self) -> None:
        if self._locked:
            self._footer.setText(
                f"<span style='color:{theme.TEXT_DIM};font-size:9px;'>"
                "locked (click-through) &middot; Ctrl+Shift+L unlock "
                "&middot; Ctrl+Shift+M hide</span>"
            )
        else:
            self._footer.setText(
                f"<span style='color:{theme.WARN};font-size:9px;'>"
                "unlocked (drag to move) &middot; Ctrl+Shift+L lock "
                "&middot; Ctrl+Shift+M hide</span>"
            )

    # ------------------------------------------------------------------
    # Event filter: forward card-area mouse events to self for drag
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        if obj is self._card:
            et = event.type()
            # In compact mode, ANY left click on the card expands.
            # The "+" button still works too, but the pip is small
            # enough that clicking the whole body is more reliable.
            if (self._compact and et == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                self._compact_btn.setChecked(False)
                return True
            if not self._locked:
                if et == QEvent.Type.MouseButtonPress:
                    self.mousePressEvent(event)
                    return True
                if et == QEvent.Type.MouseMove:
                    self.mouseMoveEvent(event)
                    return True
                if et == QEvent.Type.MouseButtonRelease:
                    self.mouseReleaseEvent(event)
                    return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Lock state (click-through toggle)
    # ------------------------------------------------------------------

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        flags = self._base_flags
        if locked:
            flags |= Qt.WindowType.WindowTransparentForInput
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        self._update_footer()

    def toggle_locked(self) -> None:
        self.set_locked(not self._locked)

    def is_locked(self) -> bool:
        return self._locked

    # ------------------------------------------------------------------
    # Manual drag handling (only when unlocked)
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):  # noqa: N802
        if (not self._locked and self._drag_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_pos = None

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-query latest match + canonical plan, render."""
        from db.database import get_connection
        from db.saved_decks import get_decks

        try:
            with get_connection() as c:
                row = c.execute(
                    "SELECT my_deck_id, opp_deck, opp_name, play_draw "
                    "FROM match_log "
                    "WHERE source='mtga_log' "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    self._subheader.setText(
                        "<i style='color:#7a8194;'>No MTGA matches yet. "
                        "Play a ranked Bo3 in Arena; the overlay updates "
                        "automatically within ~30s of match end.</i>"
                    )
                    self._plan.setText("")
                    self._notes.setVisible(False)
                    return
                # Refresh the deck dropdown so user can swap to any deck
                # that has saved plans. Only show decks WITH plans.
                deck_options = c.execute(
                    "SELECT DISTINCT d.id, d.name "
                    "FROM saved_decks d "
                    "JOIN saved_sb_plans p ON p.deck_id = d.id "
                    "ORDER BY d.name"
                ).fetchall()
                self._sync_deck_combo(
                    [(int(r["id"]), r["name"] or f"deck {r['id']}")
                     for r in deck_options]
                )

                # Resolve effective deck. Manual override (dropdown)
                # wins. Otherwise: latest match's deck if it has plans,
                # else fall back to the deck with the most plans.
                latest_opp_real = row["opp_deck"]
                latest_opp_name_real = row["opp_name"]
                latest_pd_real = row["play_draw"]
                if self._deck_override is not None:
                    effective_deck_id = self._deck_override
                else:
                    effective_deck_id = row["my_deck_id"]
                    use_fallback = effective_deck_id is None
                    if not use_fallback:
                        n_plans = c.execute(
                            "SELECT COUNT(*) FROM saved_sb_plans "
                            "WHERE deck_id = ?",
                            (effective_deck_id,),
                        ).fetchone()[0]
                        if n_plans == 0:
                            use_fallback = True
                    if use_fallback:
                        fb = c.execute(
                            "SELECT deck_id, COUNT(*) AS n FROM saved_sb_plans "
                            "GROUP BY deck_id ORDER BY n DESC LIMIT 1"
                        ).fetchone()
                        if fb is not None:
                            effective_deck_id = fb["deck_id"]
                row = {
                    "my_deck_id": effective_deck_id,
                    "opp_deck": latest_opp_real,
                    "opp_name": latest_opp_name_real,
                    "play_draw": latest_pd_real,
                }
                # Cache for the decklist panel + any other readers
                self._effective_deck_id = effective_deck_id
                my_deck_id = row["my_deck_id"]
                latest_opp = (row["opp_deck"] or "?")
                opp_name = (row["opp_name"] or "?")
                play_draw = (row["play_draw"] or "").lower()
                # Manual override (dropdown) supersedes the latest match
                if self._opp_override:
                    opp = self._opp_override
                    opp_name = f"manual: {opp}"
                else:
                    opp = latest_opp

                deck_name = "?"
                if my_deck_id is not None:
                    deck = next(
                        (d for d in get_decks() if d.get("id") == my_deck_id),
                        None,
                    )
                    if deck:
                        deck_name = deck.get("name") or "?"

                # Populate the matchup dropdown with every canonical plan
                # we have for this deck (sorted alphabetically).
                plan = None
                if my_deck_id is not None:
                    plan_rows = c.execute(
                        "SELECT opponent_archetype FROM saved_sb_plans "
                        "WHERE deck_id = ? "
                        "ORDER BY opponent_archetype",
                        (my_deck_id,),
                    ).fetchall()
                    archetype_options = [
                        r["opponent_archetype"] for r in plan_rows
                        if r["opponent_archetype"]
                    ]
                    self._sync_opp_combo(archetype_options)

                    from analysis.sb_plan_diff import _find_canonical_plan
                    plan = _find_canonical_plan(c, my_deck_id, opp)

                # Recent record vs this archetype (last 10 matches, with
                # game-level outcomes for a quick sense of how the matchup
                # has actually been going)
                record_rows = []
                opp_cards: dict[str, int] = {}
                if my_deck_id is not None and opp and opp != "?":
                    record_rows = c.execute(
                        "SELECT result, play_draw, g1_result, g2_result, "
                        "       g3_result, event_date "
                        "FROM match_log "
                        "WHERE my_deck_id = ? AND opp_deck = ? "
                        "ORDER BY id DESC LIMIT 10",
                        (my_deck_id, opp),
                    ).fetchall()
                    # Aggregate cards seen across prior matches (most-frequent
                    # first), so the user has an at-a-glance scouting report
                    # of what this archetype tends to play.
                    grp_rows = c.execute(
                        "SELECT opp_grp_ids_json FROM match_log "
                        "WHERE my_deck_id = ? AND opp_deck = ? "
                        "  AND opp_grp_ids_json IS NOT NULL "
                        "ORDER BY id DESC LIMIT 10",
                        (my_deck_id, opp),
                    ).fetchall()
                    grpid_counter: Counter = Counter()
                    for gr in grp_rows:
                        raw = gr["opp_grp_ids_json"]
                        if not raw:
                            continue
                        try:
                            ids = json.loads(raw)
                        except Exception:
                            continue
                        if isinstance(ids, list):
                            for gid in ids:
                                if isinstance(gid, int) and gid > 0:
                                    grpid_counter[gid] += 1
                    if grpid_counter:
                        from db.untapped_decklists import resolve_grpids
                        opp_cards = resolve_grpids(c, dict(grpid_counter))
        except Exception as exc:
            self._subheader.setText(
                f"<span style='color:#f04040;'>Overlay query failed: "
                f"{exc}</span>"
            )
            self._plan.setText("")
            self._notes.setVisible(False)
            return

        # ── Subheader ─────────────────────────────────────────────
        self._subheader.setText(
            f"<b style='font-size:13px;color:{theme.TEXT};'>{deck_name}</b>"
            "<br/>"
            f"<span style='color:{theme.TEXT_DIM};font-size:11px;'>"
            f"vs <b>{opp_name}</b> &mdash; {opp}"
            + (f" &middot; {play_draw}" if play_draw else "")
            + "</span>"
        )

        # ── Record vs this archetype ──────────────────────────────
        if record_rows:
            wins = sum(1 for r in record_rows
                       if (r["result"] or "").lower() == "win")
            losses = sum(1 for r in record_rows
                         if (r["result"] or "").lower() == "loss")
            wr = (wins / (wins + losses) * 100) if (wins + losses) else 0
            # Per-match win/loss chips (newest left); each chip carries
            # game-level outcomes via a tooltip-style suffix.
            chips = []
            for r in record_rows:
                res = (r["result"] or "").lower()
                color = (
                    "#80c890" if res == "win"
                    else "#d88060" if res == "loss"
                    else theme.TEXT_DIM
                )
                glyph = "W" if res == "win" else "L" if res == "loss" else "·"
                games = [
                    (r["g1_result"] or "").upper()[:1],
                    (r["g2_result"] or "").upper()[:1],
                    (r["g3_result"] or "").upper()[:1],
                ]
                games_str = "".join(g for g in games if g in ("W", "L"))
                chips.append(
                    f"<span style='color:{color};font-weight:bold;"
                    f"font-size:11px;'>{glyph}<sub "
                    f"style='color:{theme.TEXT_DIM};'>"
                    f"{games_str or '-'}</sub></span>"
                )
            wr_color = (
                "#80c890" if wr >= 55
                else "#d88060" if wr <= 45
                else theme.TEXT
            )
            self._record.setText(
                f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>"
                f"Record: </span>"
                f"<span style='color:{wr_color};font-weight:bold;"
                f"font-size:11px;'>"
                f"{wins}-{losses} ({wr:.0f}%)</span> "
                f"<span style='color:{theme.TEXT_DIM};font-size:9px;'>"
                f"last {len(record_rows)}</span>"
                + "<br/>" + "&nbsp;".join(chips)
            )
            self._record.setVisible(True)
        else:
            self._record.setVisible(False)

        # ── Cards opp tends to play ───────────────────────────────
        if opp_cards:
            # Sort by frequency (matches seen in) desc, then name; cap 12
            sorted_cards = sorted(
                opp_cards.items(), key=lambda kv: (-kv[1], kv[0])
            )[:12]
            n_matches = len(record_rows) or 1
            chips = []
            for name, count in sorted_cards:
                pct = (count / n_matches) * 100
                # Higher frequency = brighter; flex-slot cards dimmer
                col = (
                    theme.TEXT if pct >= 75
                    else theme.TEXT_DIM if pct >= 40
                    else theme.TEXT_OFF
                )
                chips.append(
                    f"<span style='color:{col};font-size:10px;'>"
                    f"{name}</span>"
                    f"<span style='color:{theme.TEXT_OFF};"
                    f"font-size:9px;'>·{count}</span>"
                )
            self._opp_cards.setText(
                f"<span style='color:{theme.TEXT_DIM};font-size:10px;'>"
                f"Cards seen ({len(record_rows)} match"
                f"{'es' if len(record_rows) != 1 else ''}):</span><br/>"
                + " &middot; ".join(chips)
            )
            self._opp_cards.setVisible(True)
        else:
            self._opp_cards.setVisible(False)

        # ── Plan (IN/OUT, compact) ───────────────────────────────
        if plan:
            in_key = "draw_in" if play_draw == "draw" else "play_in"
            out_key = "draw_out" if play_draw == "draw" else "play_out"
            try:
                in_cards = json.loads(plan.get(in_key) or "[]")
            except Exception:
                in_cards = []
            try:
                out_cards = json.loads(plan.get(out_key) or "[]")
            except Exception:
                out_cards = []
            in_c = Counter(in_cards)
            out_c = Counter(out_cards)
            difficulty = plan.get("difficulty") or "?"
            side_label = "Draw" if play_draw == "draw" else "Play"
            parts = [
                f"<hr style='border:1px solid {theme.BORDER};'/>"
                f"<b style='color:{theme.ACCENT};'>"
                f"Canonical plan ({side_label} / {difficulty})</b>"
            ]
            if in_c:
                parts.append("<b style='color:#80c890;'>IN:</b>")
                for nm, q in in_c.most_common():
                    parts.append(f"&nbsp;&nbsp;+{q} {nm}")
            if out_c:
                parts.append("<br/><b style='color:#d88060;'>OUT:</b>")
                for nm, q in out_c.most_common():
                    parts.append(f"&nbsp;&nbsp;-{q} {nm}")
            if not in_c and not out_c:
                parts.append(
                    f"<i style='color:{theme.TEXT_DIM};'>Plan exists "
                    "but has no cards on this side.</i>"
                )
            self._plan.setText("<br/>".join(parts))
        else:
            self._plan.setText(
                f"<hr style='border:1px solid {theme.BORDER};'/>"
                f"<i style='color:{theme.TEXT_DIM};'>No canonical SB plan "
                f"stored for <b>{opp}</b>. Add one via My Decks &rarr; "
                "Sideboard Plans tab.</i>"
            )

        # ── Notes (scrollable QTextEdit) ─────────────────────────
        notes_text = (plan.get("notes") if plan else None) or ""
        if notes_text.strip():
            html = (
                f"<div style='color:{theme.ACCENT};font-weight:bold;"
                "margin-bottom:4px;'>Notes</div>"
                + notes_text.replace("\n", "<br/>")
            )
            self._notes.setHtml(html)
        else:
            self._notes.setHtml(
                f"<i style='color:{theme.TEXT_DIM};'>"
                "No notes for this matchup.</i>"
            )
        # Always respect the toggle button state
        self._notes.setVisible(self._notes_toggle_btn.isChecked())

    # ------------------------------------------------------------------
    # Geometry persistence (called from MainWindow)
    # ------------------------------------------------------------------

    def geometry_tuple(self) -> tuple[int, int, int, int]:
        g = self.geometry()
        return (g.x(), g.y(), g.width(), g.height())

    def restore_geometry(self, geom) -> None:
        try:
            x, y, w, h = geom
            self.setGeometry(int(x), int(y), int(w), int(h))
        except Exception:
            pass
