"""Popup dialog showing a turn-by-turn transcript for one match.

Builds (or loads cached) transcript from `analysis.replay_transcript`,
renders as a rich-text panel inside a QDialog. Used from the Match
History sub-tab "Watch Replay" button.

v0.1 scope: life changes per turn + active player. Card-cast events
are a v0.2 (require parsing GameStateMessage.annotations[] which is
deeper structurally).
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QSizePolicy,
)
from PyQt6.QtCore import Qt

import gui.theme as theme


class ReplayTranscriptDialog(QDialog):
    """Modal popup showing a turn-by-turn match transcript."""

    def __init__(self, arena_match_id: str, opp_name: str = "",
                 my_deck_label: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Match transcript — vs {opp_name}" if opp_name
                            else "Match transcript")
        self.setMinimumSize(680, 560)
        self.setStyleSheet(f"background: {theme.BG}; color: {theme.TEXT};")

        self._arena_match_id = arena_match_id
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD,
                                  theme.SPACE_MD, theme.SPACE_MD)
        outer.setSpacing(8)

        # ── Header ────────────────────────────────────────────────
        header = QLabel(
            f"<b style='font-size:14px;color:{theme.ACCENT};'>"
            f"Match transcript</b>"
            f"<br/><span style='color:{theme.TEXT_DIM};font-size:11px;'>"
            f"{my_deck_label or '?'} vs <b>{opp_name or '?'}</b>"
            f"<br/>arena_match_id: <tt>{arena_match_id}</tt></span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(header)

        # Note about scope
        note = QLabel(
            f"<i style='color:{theme.TEXT_DIM};font-size:10px;'>"
            "v0.3 shows turn-by-turn events: cards drawn, mulligan "
            "keep/mull, lands played, spells cast, resolutions, "
            "counterspells, ability triggers/activations, declare "
            "attackers + blockers, damage dealt, tokens created, "
            "+1/+1 counters, targets, scry, surveil, bottoming, "
            "reveal, life changes. Opp cards are named only after "
            "they're revealed (cast / entered battlefield)."
            "</i>"
        )
        note.setWordWrap(True)
        outer.addWidget(note)

        # ── Transcript body ───────────────────────────────────────
        self._body = QTextEdit()
        self._body.setReadOnly(True)
        self._body.setStyleSheet(
            f"background: {theme.PANEL}; color: {theme.TEXT}; "
            f"border: 1px solid {theme.BORDER}; padding: 8px; "
            f"font-family: 'Cascadia Mono', 'Consolas', monospace; "
            f"font-size: 12px;"
        )
        self._body.setHtml(
            f"<i style='color:{theme.TEXT_DIM};'>Loading transcript…</i>"
        )
        outer.addWidget(self._body, 1)

        # ── Footer ────────────────────────────────────────────────
        footer = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh from log")
        self._refresh_btn.setStyleSheet(theme.btn_secondary())
        self._refresh_btn.setToolTip(
            "Re-parse Player.log for this match (ignore the cached JSON)."
        )
        self._refresh_btn.clicked.connect(lambda: self._load(force=True))
        footer.addWidget(self._refresh_btn)
        footer.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(theme.btn_secondary())
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addLayout(footer)

        self._worker = None
        self._load(force=False)

    def _load(self, force: bool) -> None:
        # Replace any in-flight worker -- block its signals so the late
        # result doesn't overwrite the new placeholder.
        if self._worker is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass
            self._worker = None
        self._body.setHtml(
            f"<i style='color:{theme.TEXT_DIM};'>"
            f"{'Re-parsing Player.log' if force else 'Loading transcript'}…</i>"
        )
        self._refresh_btn.setEnabled(False)

        from gui.worker_threads import DataLoadWorker

        def _do():
            from analysis.replay_transcript import build_transcript
            return build_transcript(self._arena_match_id, force_refresh=force)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_transcript_ready)
        w.error.connect(self._on_transcript_error)
        w.finished.connect(w.deleteLater)
        w.start()
        self._worker = w

    def _on_transcript_error(self, msg: str) -> None:
        self._refresh_btn.setEnabled(True)
        self._body.setHtml(
            f"<span style='color:#e07060;'>Failed to build transcript: "
            f"{msg}</span>"
        )

    def _on_transcript_ready(self, result) -> None:
        self._refresh_btn.setEnabled(True)
        if result is None:
            self._body.setHtml(
                "<span style='color:#9aa3b8;'>Match not found in "
                "Player.log / Player-prev.log. The log may have rotated "
                "since this match was played.</span>"
            )
            return

        # Render as HTML
        parts = []
        for g in result.get("games", []):
            gn = g["game_num"]
            turns = g.get("turns") or []
            if not turns:
                parts.append(
                    f"<b style='color:{theme.ACCENT};'>=== Game {gn} ===</b>"
                    f"<br/><i style='color:{theme.TEXT_DIM};'>"
                    "(no logged events)</i>"
                )
                continue
            parts.append(
                f"<b style='color:{theme.ACCENT};'>=== Game {gn} "
                f"({len(turns)} turns with logged events) ===</b>"
            )
            for t in turns:
                tn = t["turn"]
                who = t.get("active_label", "?")
                who_color = "#80c890" if who == "You" else "#d8c060"
                actions_html = "<br/>".join(
                    f"&nbsp;&nbsp;{self._format_action(a)}"
                    for a in t.get("actions", [])
                )
                parts.append(
                    f"<b>Turn {tn}</b> &nbsp;"
                    f"<span style='color:{who_color};'>"
                    f"({who}'s turn)</span><br/>{actions_html}"
                )
            parts.append("")  # spacing between games
        if not parts:
            self._body.setHtml(
                "<i style='color:#9aa3b8;'>No game events parsed.</i>"
            )
            return
        self._body.setHtml("<br/>".join(parts))

    @staticmethod
    def _format_action(a: str) -> str:
        """Color-code action strings for readability."""
        if "life:" in a:
            # Damage taken: red; healing: green
            if "(-" in a:
                return f"<span style='color:#d88060;'>{a}</span>"
            elif "(+" in a:
                return f"<span style='color:#80c890;'>{a}</span>"
        return a
