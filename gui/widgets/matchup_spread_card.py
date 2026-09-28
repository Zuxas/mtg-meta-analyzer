"""Matchup spread card: your record per opponent, sample-size honest.

KPI strip (record / win rate / on the play / on the draw) over a list of
opponents with a WinRateBar (fades on small samples), a W-L pill and a note.
Advice appears only at personal_spread.MIN_ADVICE_N+ games; unknown opponents
are shown last and never rated. Competitive/All drops casual games.
Data: analysis.personal_spread (read-only), loaded off the GUI thread.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

import gui.theme as theme
from gui.widgets.kit import KpiStrip, RecordPill, SegmentedControl, WinRateBar, _set_kit

_SEV_COLOR = {
    "critical": theme.LOSS, "warning": theme.WARN, "low": theme.WARN,
    "strong": theme.WIN, "ok": theme.TEXT_DIM, None: theme.TEXT_OFF,
}
_SEV_LABEL = {"critical": "CRITICAL", "warning": "BELOW META", "low": "LOSING",
              "strong": "STRONG", "ok": "", None: ""}


def _pct(v):
    return "--" if v is None else f"{v * 100:.0f}%"


class MatchupSpreadCard(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        _set_kit(self, "card")
        self._workers: list = []
        self._format: str | None = None
        self._gen = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD, theme.SPACE_MD)
        lay.setSpacing(theme.SPACE_SM)

        head = QHBoxLayout()
        title = QLabel("Matchup spread")
        title.setStyleSheet(f"font-size: {theme.FONT_LG}px; font-weight: 700;")
        head.addWidget(title)
        head.addStretch()
        self._deck = QComboBox()
        self._deck.setMinimumWidth(180)
        self._deck.currentIndexChanged.connect(lambda _i: self.reload())
        head.addWidget(self._deck)
        self._mode = SegmentedControl(["Competitive", "All"], "All")
        self._mode.valueChanged.connect(lambda _v: self.reload())
        head.addWidget(self._mode)
        lay.addLayout(head)

        self._kpis = KpiStrip([("rec", "Record"), ("wr", "Win rate"),
                               ("play", "On the play"), ("draw", "On the draw")])
        lay.addWidget(self._kpis)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: {theme.FONT_SM}px;")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self._rows.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._rows_host)
        lay.addWidget(scroll, 1)

    # ---------------------------------------------------------------- public
    def load_decks(self, preferred: str | None = None) -> None:
        """Fill the deck picker (every deck with results, most played first)."""
        from db.database import get_connection
        from analysis.personal_spread import deck_choices
        try:
            with get_connection() as con:
                choices = deck_choices(con)
        except Exception as e:  # never let a DB error escape into a Qt slot
            self._status.setText(f"Could not load decks: {e}")
            return
        self._deck.blockSignals(True)
        self._deck.clear()
        for name, n in choices:
            self._deck.addItem(f"{name}  ({n})", name)
        idx = self._deck.findData(preferred) if preferred else -1
        self._deck.setCurrentIndex(idx if idx >= 0 else (0 if choices else -1))
        self._deck.blockSignals(False)
        self.reload()

    def set_format(self, fmt: str | None) -> None:
        self._format = fmt or None
        self.reload()

    def deck(self) -> str | None:
        return self._deck.currentData()

    def reload(self) -> None:
        deck = self.deck()
        if not deck:
            self._render(None)
            return
        from gui.worker_threads import DataLoadWorker
        self._gen += 1
        gen, fmt = self._gen, self._format
        competitive = self._mode.value() == "Competitive"

        def _do():
            from db.database import get_connection
            from analysis.personal_spread import matchup_spread
            with get_connection() as con:
                return gen, matchup_spread(con, deck, fmt, competitive_only=competitive)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_result)
        w.error.connect(lambda msg: self._status.setText(f"Could not load: {msg}"))
        w.finished.connect(w.deleteLater)
        self._workers.append(w)
        w.start()

    def cleanup(self) -> None:
        from gui.worker_utils import stop_worker
        for w in self._workers:
            stop_worker(w)
        self._workers.clear()

    # ---------------------------------------------------------------- render
    def _on_result(self, payload) -> None:
        try:
            gen, data = payload
            if gen == self._gen:  # a newer request superseded this one
                self._render(data)
        except Exception as e:  # PyQt6 aborts the process on a raising slot
            self._status.setText(f"Render error: {e}")

    def _clear_rows(self) -> None:
        while self._rows.count() > 1:
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render(self, data) -> None:
        self._clear_rows()
        if not data or not data["kpis"]["matches"]:
            for k in ("rec", "wr", "play", "draw"):
                self._kpis.set(k, "--", "")
            self._status.setText("No decided matches for this deck and filter.")
            return
        k = data["kpis"]
        self._kpis.set("rec", f"{k['wins']}-{k['losses']}", f"{k['matches']} matches",
                       tone="win" if k["wins"] > k["losses"] else "loss" if k["losses"] > k["wins"] else "neutral")
        self._kpis.set("wr", _pct(k["wr"]), "")
        self._kpis.set("play", _pct(k["play_wr"]), f"n={k['play_n']}")
        self._kpis.set("draw", _pct(k["draw_wr"]), f"n={k['draw_n']}")

        scope = "all formats" if not data["format"] else data["format"]
        bits = [f"{len(data['rows'])} opponents, {scope}"]
        if not data["format"]:
            bits.append("pick a format to compare against the meta")
        elif not data["has_meta"]:
            bits.append("no meta win rates for this deck")
        from analysis.personal_spread import MIN_ADVICE_N
        bits.append(f"advice from {MIN_ADVICE_N}+ games")
        self._status.setText(" · ".join(bits))

        for r in data["rows"]:
            self._rows.insertWidget(self._rows.count() - 1, self._row(
                r["opponent"], r["wins"], r["losses"], r["wr"], r["n"], r["severity"], r["note"]))
        u = data["unknown"]
        if u:
            self._rows.insertWidget(self._rows.count() - 1, self._row(
                "Unknown opponent", u["wins"], u["losses"], u["wr"], u["n"], None,
                "deck not identified -- not rated", italic=True))

    def _row(self, name, wins, losses, wr, n, severity, note, italic=False) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(theme.SPACE_SM)
        lbl = QLabel(name)
        lbl.setFixedWidth(170)
        lbl.setToolTip(name)
        if italic:
            lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-style: italic;")
        h.addWidget(lbl)
        bar = WinRateBar(wr, n)
        bar.setFixedWidth(150)
        bar.setToolTip(f"{wins}-{losses} ({n} matches)")
        h.addWidget(bar)
        h.addWidget(RecordPill(wins, losses))
        tag = _SEV_LABEL.get(severity, "")
        text = f"{tag}  {note}".strip() if tag else note
        n_lbl = QLabel(text)
        n_lbl.setStyleSheet(f"color: {_SEV_COLOR.get(severity, theme.TEXT_DIM)};"
                            f" font-size: {theme.FONT_SM}px;")
        h.addWidget(n_lbl, 1)
        return row
