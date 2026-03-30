"""
Tab — New Set Break Protocol

Paste spoilers from a new set → Claude classifies each card's competitive
impact against the current meta. Outputs a ranked breakdown of which cards
matter, which archetypes gain tools, and what sideboard tech to watch.

Requires an Anthropic API key (same one used by Ask Claude tab).
"""
import os
import re
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QMessageBox, QSplitter, QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor

import gui.theme as theme


# ---------------------------------------------------------------------------
# Streaming worker (reuses Ask Claude pattern)
# ---------------------------------------------------------------------------

class _AnalysisWorker(QThread):
    chunk = pyqtSignal(str)
    done  = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, messages: list, system: str, api_key: str):
        super().__init__()
        self._messages = messages
        self._system   = system
        self._api_key  = api_key

    def run(self):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self._api_key)
            with client.messages.stream(
                model="claude-opus-4-6",
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=self._system,
                messages=self._messages,
            ) as stream:
                for text in stream.text_stream:
                    self.chunk.emit(text)
            self.done.emit()
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an elite Magic: The Gathering set analyst working inside a competitive \
meta analysis tool. Your job is to evaluate new card spoilers against the \
current competitive meta and identify which cards will see play.

For EACH card that has competitive potential, classify it into one or more buckets:

**🔴 Rate Outlier** — raw power level above the current bar (efficient stats, \
undercosted effect, immediate board impact)
**⚙️ Engine Piece** — enables a new strategy or significantly upgrades an \
existing engine (combo enabler, card advantage loop, mana engine)
**🔗 Enabler** — makes an existing archetype more consistent or unlocks a \
card that was previously too weak (fixing mana, tutoring, redundancy)
**🛡️ SB Breaker** — answers a specific meta problem (hate card, silver \
bullet, new angle of attack against a dominant deck)
**⬆️ Upgrade Card** — strictly or functionally better than a card already \
seeing play in a known archetype

After classifying individual cards, provide TWO summary sections:

## Impact by Archetype
For each top meta archetype, list which new cards slot in (main or side), \
what they replace, and why.

## Top 10 Most Likely to Matter
Ranked list of the cards most likely to see competitive play, with a \
one-line reason for each.

Be specific. Reference actual meta decks and real card names. If a card \
is unplayable in the current meta, skip it — don't waste time on limited-only \
cards or casual inclusions. Focus on Constructed impact.

When uncertain, say "speculative" rather than guessing confidently."""


# ---------------------------------------------------------------------------
# Meta context builder
# ---------------------------------------------------------------------------

def _build_meta_context(fmt: str) -> str:
    """Fetch top archetypes + key cards for the selected format."""
    try:
        from db.database import get_combined_connection
        since = (datetime.now() - timedelta(weeks=4)).strftime("%Y%m%d")
        _dk = ("CASE WHEN instr(e.date,'/')>0 "
               "THEN '20'||substr(e.date,7,2)||substr(e.date,4,2)||substr(e.date,1,2) "
               "ELSE replace(e.date,'-','') END")
        conn = get_combined_connection()
        try:
            rows = conn.execute(f"""
                SELECT d.archetype,
                       COUNT(*) AS apps,
                       AVG(CASE WHEN d.placement <= 8 THEN 1.0 ELSE 0.0 END) AS top8_rate
                FROM decks d JOIN events e ON e.id = d.event_id
                WHERE lower(e.format) = lower(?)
                  AND ({_dk}) >= ?
                  AND d.archetype IS NOT NULL
                  AND d.archetype != ''
                GROUP BY d.archetype ORDER BY apps DESC LIMIT 15
            """, [fmt, since]).fetchall()
        finally:
            conn.close()
        if not rows:
            return "\n\n(No meta data available for this format.)"
        lines = [f"\n\n## Current {fmt.capitalize()} Meta (last 4 weeks)"]
        for r in rows:
            lines.append(
                f"- **{r['archetype']}** — {r['apps']} appearances, "
                f"{r['top8_rate']*100:.0f}% top-8 rate"
            )
        return "\n".join(lines)
    except Exception:
        return "\n\n(Could not load meta data.)"


# ---------------------------------------------------------------------------
# Lightweight markdown → HTML (same as ask_claude.py)
# ---------------------------------------------------------------------------

_RESULT_STYLE = ("background:#1a2235; border-left:3px solid #3cb44b; "
                 "padding:10px 12px; margin:4px 0; border-radius:3px;")
_ERR_STYLE = ("background:#3a1515; border-left:3px solid #e6194b; "
              "padding:8px 10px; margin:4px 0; border-radius:3px;")


def _md_to_html(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r'<code style="background:#2a3045;">\1</code>', text)
    lines, out = text.split("\n"), []
    for line in lines:
        if line.startswith(("• ", "- ")):
            out.append(f"&nbsp;&nbsp;• {line[2:]}")
        elif line.startswith("## "):
            out.append(f"<b style='font-size:13px;'>{line[3:]}</b>")
        elif line.startswith("# "):
            out.append(f"<b style='font-size:14px;'>{line[2:]}</b>")
        else:
            out.append(line)
    return "<br>".join(out)


# ---------------------------------------------------------------------------
# Tab widget
# ---------------------------------------------------------------------------

class SetAnalysisTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._streaming_buf = ""
        self._build_ui()

    def cleanup(self):
        if self._worker is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass
            self._worker = None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header
        header = QLabel("NEW SET BREAK PROTOCOL")
        header.setFont(QFont("Orbitron", 14, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {theme.ACCENT};")
        layout.addWidget(header)

        desc = QLabel(
            "Paste new set spoilers below. Claude will classify each card's "
            "competitive impact against the current meta and identify which "
            "archetypes gain new tools."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; margin-bottom: 4px;")
        layout.addWidget(desc)

        # Controls row
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy", "pauper"])
        self._fmt.setFixedWidth(110)
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("Set name:"))
        self._set_name = QComboBox()
        self._set_name.setEditable(True)
        self._set_name.setFixedWidth(200)
        self._set_name.setPlaceholderText("e.g. Tarkir: Dragonstorm")
        ctrl.addWidget(self._set_name)

        ctrl.addStretch()

        self._analyze_btn = QPushButton("Analyze Set")
        self._analyze_btn.setStyleSheet(theme.btn_primary())
        self._analyze_btn.setFixedWidth(120)
        self._analyze_btn.clicked.connect(self._analyze)
        ctrl.addWidget(self._analyze_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setStyleSheet(theme.btn_secondary())
        self._clear_btn.clicked.connect(self._clear)
        ctrl.addWidget(self._clear_btn)

        layout.addLayout(ctrl)

        # Splitter: input (left) / results (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: card list input
        left = QFrame()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lbl = QLabel("Card List (one per line: Name or Name — Rules Text)")
        left_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        left_lay.addWidget(left_lbl)

        self._input = QTextEdit()
        self._input.setPlaceholderText(
            "Paste card spoilers here, one per line.\n\n"
            "Accepted formats:\n"
            "  Card Name\n"
            "  Card Name {2}{W}{W} — Creature text here\n"
            "  Card Name | 3WW | Creature — Human | text\n\n"
            "More detail = better analysis. Include mana cost,\n"
            "type line, and rules text when available."
        )
        self._input.setFont(QFont("Consolas", 10))
        self._input.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 4px;"
        )
        left_lay.addWidget(self._input)
        splitter.addWidget(left)

        # Right: analysis results
        right = QFrame()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        self._result_lbl = QLabel("Analysis Results")
        self._result_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        right_lay.addWidget(self._result_lbl)

        self._results = QTextEdit()
        self._results.setReadOnly(True)
        self._results.setFont(QFont("Consolas", 10))
        self._results.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 4px;"
        )
        right_lay.addWidget(self._results)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        # Status bar
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        layout.addWidget(self._status)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _get_api_key(self) -> str:
        from gui.tabs.settings import load_preferences
        prefs = load_preferences()
        return prefs.get("anthropic_api_key", "").strip()

    def _clear(self):
        self._results.clear()
        self._streaming_buf = ""
        self._status.setText("")

    def _analyze(self):
        api_key = self._get_api_key()
        if not api_key:
            QMessageBox.warning(
                self, "No API Key",
                "Set your Anthropic API key in Settings → AI Assistant first."
            )
            return

        card_text = self._input.toPlainText().strip()
        if not card_text:
            QMessageBox.warning(self, "No Cards", "Paste card spoilers in the left panel first.")
            return

        if self._worker and self._worker.isRunning():
            return

        # Count cards (rough: non-empty lines)
        card_count = len([l for l in card_text.split("\n") if l.strip()])
        fmt = self._fmt.currentText()
        set_name = self._set_name.currentText().strip() or "New Set"

        # Build meta context
        meta_ctx = _build_meta_context(fmt)

        # Build user message
        user_msg = (
            f"## Set: {set_name}\n"
            f"## Format: {fmt.capitalize()}\n"
            f"## Cards ({card_count} total):\n\n"
            f"{card_text}"
        )

        system = _SYSTEM + meta_ctx

        # Start analysis
        self._results.clear()
        self._streaming_buf = ""
        self._status.setText(f"Analyzing {card_count} cards against {fmt.capitalize()} meta...")
        self._analyze_btn.setEnabled(False)
        self._result_lbl.setText(f"Analysis Results — {set_name} for {fmt.capitalize()}")

        # Clean up previous worker
        if getattr(self, "_worker", None) is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass
            self._worker = None

        self._worker = _AnalysisWorker(
            messages=[{"role": "user", "content": user_msg}],
            system=system,
            api_key=api_key,
        )
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.done.connect(self._worker.deleteLater)
        self._worker.done.connect(lambda: setattr(self, "_worker", None))
        self._worker.error.connect(self._worker.deleteLater)
        self._worker.error.connect(lambda _: setattr(self, "_worker", None))
        self._worker.start()

    def _on_chunk(self, text: str):
        self._streaming_buf += text
        cursor = self._results.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._results.setTextCursor(cursor)
        self._results.ensureCursorVisible()

    def _on_done(self):
        self._status.setText(
            f"Analysis complete — {datetime.now().strftime('%H:%M:%S')}"
        )
        self._analyze_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self._results.append(f"\n\n--- ERROR ---\n{msg}")
        self._status.setText("Analysis failed.")
        self._analyze_btn.setEnabled(True)
