"""
Tab — New Set Break Protocol

Fetch spoilers from Mythic Spoiler or paste manually → Claude classifies
each card's competitive impact against the current meta with format
legality awareness.

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
# Workers
# ---------------------------------------------------------------------------

class _AnalysisWorker(QThread):
    """Streams Claude API response for set analysis."""
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


class _FetchWorker(QThread):
    """Fetches card data from Mythic Spoiler + Scryfall in background."""
    finished = pyqtSignal(list)   # list[dict]
    error    = pyqtSignal(str)

    def __init__(self, set_code: str):
        super().__init__()
        self._set_code = set_code

    def run(self):
        try:
            from scrapers.mythicspoiler_scraper import fetch_set_cards
            cards = fetch_set_cards(self._set_code)
            self.finished.emit(cards)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an elite Magic: The Gathering set analyst working inside a competitive \
meta analysis tool. Your job is to evaluate new card spoilers against the \
current competitive meta and identify which cards will see play.

IMPORTANT: You are analyzing cards for {format} format ONLY. Only recommend \
cards that are legal in {format}. If a card is not legal in this format, \
skip it entirely.

For EACH card that has competitive potential in {format}, classify it into \
one or more buckets:

**Rate Outlier** — raw power level above the current bar (efficient stats, \
undercosted effect, immediate board impact)
**Engine Piece** — enables a new strategy or significantly upgrades an \
existing engine (combo enabler, card advantage loop, mana engine)
**Enabler** — makes an existing archetype more consistent or unlocks a \
card that was previously too weak (fixing mana, tutoring, redundancy)
**SB Breaker** — answers a specific meta problem (hate card, silver \
bullet, new angle of attack against a dominant deck)
**Upgrade Card** — strictly or functionally better than a card already \
seeing play in a known archetype

After classifying individual cards, provide TWO summary sections:

## Impact by Archetype
For each top {format} meta archetype, list which new cards slot in \
(main or side), what they replace, and why.

## Top 10 Most Likely to Matter
Ranked list of the cards most likely to see competitive play in {format}, \
with a one-line reason for each.

Be specific. Reference actual {format} meta decks and real card names. \
If a card is unplayable in the current {format} meta, skip it — don't \
waste time on limited-only cards or casual inclusions. Focus on \
Constructed impact.

When uncertain, say "speculative" rather than guessing confidently."""


# ---------------------------------------------------------------------------
# Meta context builder
# ---------------------------------------------------------------------------

def _build_meta_context(fmt: str) -> str:
    """Fetch top archetypes for the selected format."""
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
                GROUP BY d.archetype ORDER BY apps DESC LIMIT 10
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
# Tab widget
# ---------------------------------------------------------------------------

class SetAnalysisTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._fetch_worker = None
        self._streaming_buf = ""
        self._fetched_cards: list[dict] = []
        self._build_ui()

    def cleanup(self):
        from gui.worker_utils import stop_worker
        for attr in ("_worker", "_fetch_worker"):
            stop_worker(getattr(self, attr, None))
            setattr(self, attr, None)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)
        layout.setSpacing(6)

        # Header
        header = QLabel("NEW SET BREAK PROTOCOL")
        header.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {theme.ACCENT};")
        layout.addWidget(header)

        desc = QLabel(
            "Fetch card data from Mythic Spoiler or paste spoilers manually. "
            "Claude classifies each card's competitive impact against the "
            "current meta for the selected format."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px; margin-bottom: 4px;")
        layout.addWidget(desc)

        # Row 1: Format + Set code + Fetch button
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy", "pauper"])
        self._fmt.setFixedWidth(110)
        row1.addWidget(self._fmt)

        row1.addWidget(QLabel("Set code:"))
        self._set_code = QComboBox()
        self._set_code.setEditable(True)
        self._set_code.setFixedWidth(120)
        self._set_code.setToolTip("3-letter WotC set code (e.g. TDM, FDN, EOE)")
        # Populate with known sets
        from scrapers.mythicspoiler_scraper import KNOWN_SETS
        for code, (name, _date) in sorted(KNOWN_SETS.items(),
                                           key=lambda x: x[1][1], reverse=True):
            self._set_code.addItem(f"{code} — {name}", code)
        row1.addWidget(self._set_code)

        self._fetch_btn = QPushButton("Fetch from Mythic Spoiler")
        self._fetch_btn.setStyleSheet(theme.btn_primary())
        self._fetch_btn.setToolTip("Download card list from mythicspoiler.com + enrich from Scryfall")
        self._fetch_btn.clicked.connect(self._fetch_cards)
        row1.addWidget(self._fetch_btn)

        row1.addStretch()

        self._legality_lbl = QLabel("")
        self._legality_lbl.setStyleSheet(f"font-size: 11px;")
        row1.addWidget(self._legality_lbl)

        layout.addLayout(row1)

        # Row 2: Analyze + Clear
        row2 = QHBoxLayout()
        self._analyze_btn = QPushButton("Analyze Set")
        self._analyze_btn.setStyleSheet(theme.btn_primary())
        self._analyze_btn.setFixedWidth(120)
        self._analyze_btn.clicked.connect(self._analyze)
        row2.addWidget(self._analyze_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setStyleSheet(theme.btn_secondary())
        self._clear_btn.clicked.connect(self._clear)
        row2.addWidget(self._clear_btn)

        row2.addStretch()

        self._card_count_lbl = QLabel("")
        self._card_count_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        row2.addWidget(self._card_count_lbl)

        layout.addLayout(row2)

        # Splitter: input (left) / results (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: card list input
        left = QFrame()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lbl = QLabel(
            "Card List — fetched from Mythic Spoiler or paste manually "
            "(Name ManaCost — Type [rules text])"
        )
        left_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        left_lbl.setWordWrap(True)
        left_lay.addWidget(left_lbl)

        self._input = QTextEdit()
        self._input.setPlaceholderText(
            "Click 'Fetch from Mythic Spoiler' to auto-populate,\n"
            "or paste card spoilers here manually.\n\n"
            "Accepted formats:\n"
            "  Card Name\n"
            "  Card Name {2}{W}{W} — Creature text here\n"
            "  Card Name | 3WW | Creature — Human | text\n\n"
            "More detail = better analysis."
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

        # Wire format change to legality check
        self._fmt.currentIndexChanged.connect(self._update_legality)
        self._set_code.currentIndexChanged.connect(self._update_legality)
        self._set_code.editTextChanged.connect(self._update_legality)

    # ------------------------------------------------------------------
    # Legality check
    # ------------------------------------------------------------------

    def _get_set_code(self) -> str:
        """Extract the set code from the combo (handles 'TDM — Name' format)."""
        text = self._set_code.currentText().strip()
        # If it contains ' — ', take the code before it
        if " — " in text:
            text = text.split(" — ")[0].strip()
        # Also try userData
        data = self._set_code.currentData()
        if data:
            return data.upper()
        return text.upper()

    def _update_legality(self):
        code = self._get_set_code()
        fmt = self._fmt.currentText()
        if not code or len(code) < 2:
            self._legality_lbl.setText("")
            return

        from scrapers.mythicspoiler_scraper import is_set_legal_in_format
        is_legal, reason = is_set_legal_in_format(code, fmt)

        if is_legal:
            self._legality_lbl.setText(f"<span style='color:#3cb44b;'>{reason}</span>")
        else:
            self._legality_lbl.setText(
                f"<span style='color:#f58231;'>Warning: {reason} "
                f"Cards may not be legal in {fmt.capitalize()}.</span>"
            )

    # ------------------------------------------------------------------
    # Fetch from Mythic Spoiler
    # ------------------------------------------------------------------

    def _fetch_cards(self):
        if self._fetch_worker and self._fetch_worker.isRunning():
            return

        code = self._get_set_code()
        if not code or len(code) < 2:
            QMessageBox.warning(self, "No Set Code", "Enter a set code (e.g. TDM, FDN, EOE).")
            return

        self._status.setText(f"Fetching {code} from Mythic Spoiler...")
        self._fetch_btn.setEnabled(False)

        self._fetch_worker = _FetchWorker(code)
        self._fetch_worker.finished.connect(self._on_fetch_done)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.finished.connect(self._fetch_worker.deleteLater)
        self._fetch_worker.finished.connect(lambda: setattr(self, "_fetch_worker", None))
        self._fetch_worker.error.connect(self._fetch_worker.deleteLater)
        self._fetch_worker.error.connect(lambda _: setattr(self, "_fetch_worker", None))
        self._fetch_worker.start()

    def _on_fetch_done(self, cards: list):
        self._fetch_btn.setEnabled(True)
        self._fetched_cards = cards

        if not cards:
            self._status.setText("No cards found. Check the set code or paste manually.")
            return

        # Format cards for the text area
        from scrapers.mythicspoiler_scraper import format_cards_for_analysis
        text = format_cards_for_analysis(cards)
        self._input.setPlainText(text)
        self._card_count_lbl.setText(f"{len(cards)} cards loaded")
        self._status.setText(
            f"Loaded {len(cards)} cards from Mythic Spoiler + Scryfall"
        )
        self._update_legality()

    def _on_fetch_error(self, msg: str):
        self._fetch_btn.setEnabled(True)
        self._status.setText(f"Fetch failed: {msg}")
        QMessageBox.warning(self, "Fetch Error", f"Could not fetch cards:\n{msg}")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _get_api_key(self) -> str:
        from gui.tabs.settings import load_preferences
        prefs = load_preferences()
        return prefs.get("anthropic_api_key", "").strip()

    def _clear(self):
        self._results.clear()
        self._streaming_buf = ""
        self._status.setText("")
        self._card_count_lbl.setText("")

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
            QMessageBox.warning(self, "No Cards",
                                "Fetch cards or paste spoilers in the left panel first.")
            return

        if self._worker and self._worker.isRunning():
            return

        card_count = len([l for l in card_text.split("\n") if l.strip()])
        fmt = self._fmt.currentText()
        code = self._get_set_code()

        from scrapers.mythicspoiler_scraper import KNOWN_SETS
        set_info = KNOWN_SETS.get(code, (code, ""))
        set_name = set_info[0] if isinstance(set_info, tuple) else code

        # Check legality and build warning
        from scrapers.mythicspoiler_scraper import is_set_legal_in_format
        is_legal, reason = is_set_legal_in_format(code, fmt)

        legality_note = ""
        if not is_legal:
            legality_note = (
                f"\n\nIMPORTANT: {reason} Nevertheless, analyze these cards "
                f"for potential {fmt.capitalize()} impact if they were legal, "
                f"but clearly note that legality is uncertain."
            )

        # Build meta context
        meta_ctx = _build_meta_context(fmt)

        # Build system prompt with format inserted
        system = _SYSTEM.format(format=fmt.capitalize()) + meta_ctx

        # Build user message
        user_msg = (
            f"## Set: {set_name} ({code})\n"
            f"## Format: {fmt.capitalize()}\n"
            f"## Cards ({card_count} total):\n\n"
            f"{card_text}"
            f"{legality_note}"
        )

        # Start analysis
        self._results.clear()
        self._streaming_buf = ""
        self._status.setText(f"Analyzing {card_count} cards for {fmt.capitalize()}...")
        self._analyze_btn.setEnabled(False)
        self._result_lbl.setText(
            f"Analysis Results — {set_name} for {fmt.capitalize()}"
        )

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
