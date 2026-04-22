"""
Tab — Ask Claude  (optional, shown only when an Anthropic API key is saved)

A streaming chat interface backed by claude-opus-4-6.
Automatically injects live meta context (top archetypes, recent standings)
from the local database so Claude can give format-aware advice.

API key: set in Settings → AI Assistant section → saved to preferences.json.
The tab is hidden when no key is configured; it appears automatically once
the user saves a valid key.
"""
import os
import re
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QComboBox, QCheckBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor

import gui.theme as theme
from gui.icons_util import btn_icon


# ---------------------------------------------------------------------------
# Streaming worker
# ---------------------------------------------------------------------------

class _StreamWorker(QThread):
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
                max_tokens=4096,
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
# System prompt + meta context
# ---------------------------------------------------------------------------

_SYSTEM_BASE = """You are an expert Magic: The Gathering analyst embedded in the \
MTG Meta Analyzer tool. You have deep knowledge of competitive MTG formats — \
Standard, Pioneer, Modern, and Legacy — and can help users with:
• Deck building and optimisation
• Sideboard construction and matchup advice
• Meta analysis and format positioning
• Card evaluation and synergies
• Tournament preparation

Be concise but thorough. Use bullet points and markdown formatting where it \
helps clarity. When recommending cards always explain why. Never make up card \
names or abilities — if uncertain, say so."""


def _fetch_meta_context(fmt: str) -> str:
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
                       AVG(CASE WHEN d.placement = 1 THEN 1.0 ELSE 0.0 END) AS wr
                FROM decks d JOIN events e ON e.id = d.event_id
                WHERE lower(e.format) = lower(?)
                  AND ({_dk}) >= ?
                  AND d.archetype IS NOT NULL
                GROUP BY d.archetype ORDER BY apps DESC LIMIT 15
            """, [fmt, since]).fetchall()
        finally:
            conn.close()
        if not rows:
            return ""
        lines = [f"\n\n## Current {fmt.capitalize()} meta (last 4 weeks)"]
        for r in rows:
            lines.append(
                f"- **{r['archetype']}** — {r['apps']} top finishes, "
                f"{r['wr']*100:.0f}% first-place rate"
            )
        return "\n".join(lines)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Lightweight markdown → HTML
# ---------------------------------------------------------------------------

_USER_STYLE = theme.chat_bubble_style(theme.ACCENT)
_ASST_STYLE = theme.chat_bubble_style(theme.OK)
_ERR_STYLE  = theme.chat_bubble_style(theme.ERR)


def _md_to_html(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*",     r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", rf'<code style="{theme.inline_code_style()}">\1</code>', text)
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

class AskClaudeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: list[dict] = []
        self._worker = None
        self._streaming_buf = ""
        self._build_ui()

    def cleanup(self):
        """Stop streaming worker. Called by MainWindow on app exit."""
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
        layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)
        layout.setSpacing(6)

        # Options row
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.setFixedWidth(110)
        opt_row.addWidget(self._fmt)

        self._ctx_check = QCheckBox("Include meta context")
        self._ctx_check.setChecked(True)
        self._ctx_check.setToolTip(
            "Injects top archetypes and standings from your local DB into the prompt."
        )
        opt_row.addWidget(self._ctx_check)
        opt_row.addStretch()

        self._clear_btn = QPushButton(btn_icon("delete"), "Clear chat")
        self._clear_btn.setStyleSheet(theme.btn_secondary())
        self._clear_btn.clicked.connect(self._clear_chat)
        opt_row.addWidget(self._clear_btn)
        layout.addLayout(opt_row)

        # Chat display
        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setFont(QFont("Consolas", 10))
        self._chat.setStyleSheet(
            f"background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
            "border-radius: 3px; padding: 4px;"
        )
        layout.addWidget(self._chat, 1)

        # Input row
        input_row = QHBoxLayout()
        self._input = QTextEdit()
        self._input.setPlaceholderText(
            "Ask anything — deck advice, matchup tips, sideboard guide, card choices…"
        )
        self._input.setMaximumHeight(80)
        self._input.setFont(QFont("Consolas", 10))
        self._input.installEventFilter(self)
        input_row.addWidget(self._input, 1)

        self._send_btn = QPushButton(btn_icon("run"), "Send")
        self._send_btn.setStyleSheet(theme.btn_primary())
        self._send_btn.setFixedWidth(70)
        self._send_btn.setFixedHeight(78)
        self._send_btn.clicked.connect(self._send)
        input_row.addWidget(self._send_btn)
        layout.addLayout(input_row)

        hint = QLabel("Shift+Enter = new line   |   Enter = send   |   API key: Settings → AI Assistant")
        hint.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 10px;")
        layout.addWidget(hint)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent):
                if (event.key() == Qt.Key.Key_Return
                        and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Key access
    # ------------------------------------------------------------------

    def _get_api_key(self) -> str:
        from gui.tabs.settings import load_preferences
        prefs = load_preferences()
        return prefs.get("anthropic_api_key", "").strip()

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def _append_html(self, html: str):
        self._chat.moveCursor(QTextCursor.MoveOperation.End)
        self._chat.insertHtml(html)
        self._chat.moveCursor(QTextCursor.MoveOperation.End)

    def _append_error(self, text: str):
        self._append_html(
            f'<div style="{_ERR_STYLE}"><b style="color:#e6194b;">Error</b><br>'
            f'{_md_to_html(text)}</div><br>'
        )

    def _clear_chat(self):
        self._chat.clear()
        self._messages.clear()
        self._streaming_buf = ""

    def _send(self):
        api_key = self._get_api_key()
        if not api_key:
            self._append_error(
                "No API key configured. Go to Settings → AI Assistant and save your key."
            )
            return

        text = self._input.toPlainText().strip()
        if not text or (self._worker and self._worker.isRunning()):
            return

        self._input.clear()

        # Show user message
        self._append_html(
            f'<div style="{_USER_STYLE}"><b style="color:#5eb5cf;">You</b><br>'
            f'{_md_to_html(text)}</div><br>'
        )
        self._messages.append({"role": "user", "content": text})

        # Build system prompt
        system = _SYSTEM_BASE
        if self._ctx_check.isChecked():
            system += _fetch_meta_context(self._fmt.currentText())

        # Start streaming
        self._streaming_buf = ""
        self._append_html(
            f'<div style="{_ASST_STYLE}"><b style="color:#3cb44b;">Claude</b><br>'
        )
        self._send_btn.setEnabled(False)

        # Clean up previous worker before replacing
        if getattr(self, "_worker", None) is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass
            self._worker = None

        self._worker = _StreamWorker(
            messages=list(self._messages),
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
        cursor = self._chat.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._chat.setTextCursor(cursor)
        self._chat.ensureCursorVisible()

    def _on_done(self):
        self._append_html("</div><br>")
        self._messages.append({"role": "assistant", "content": self._streaming_buf})
        self._streaming_buf = ""
        self._send_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self._append_html("</div>")
        self._append_error(msg)
        if self._messages and self._messages[-1]["role"] == "user":
            self._messages.pop()
        self._streaming_buf = ""
        self._send_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # External API
    # ------------------------------------------------------------------

    def ask(self, question: str, fmt: str = "standard"):
        """Pre-fill and send a question from another tab."""
        self._fmt.setCurrentText(fmt)
        self._input.setPlainText(question)
        self._send()
