"""
Tab — Deck Analyzer
Paste any decklist in Arena export format, run Blunder Detection +
Chapin Principles evaluation, see results side-by-side.

"Load avg deck" row lets you pick any archetype from the DB and populate
the text box with its average decklist, ready to analyze or export.
"""
import re
from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QComboBox, QFrame, QLineEdit,
    QGroupBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
import gui.theme as theme
from gui.worker_threads import DataLoadWorker


# ------------------------------------------------------------------
# Decklist parser
# ------------------------------------------------------------------

def parse_arena_decklist(text: str):
    """
    Parse a decklist in any common tournament/client export format.

    Section headers recognised (case-insensitive, leading // or trailing : ok):
      Mainboard  : "Deck", "Commander"
      Sideboard  : "Sideboard", "Sideboard:", "SIDEBOARD:", "SB:",
                   "// Sideboard", "// SB"
      Inline SB  : "SB: 2 Negate"  (prefix form used by some tools)

    Blank-line fallback: when NO explicit sideboard marker is present in the
    text, a blank line between two card groups is treated as the main/side
    boundary (standard MTGO copy-paste without the 'Sideboard' header).

    Card lines: "4 Lightning Bolt", "4x Lightning Bolt",
                "4 Lightning Bolt (M11) 149"  — set/collector suffix stripped.

    Returns (mainboard, sideboard) as {name: quantity} dicts.
    """
    _SIDE_KEYWORDS = {"sideboard", "sideboard:", "sb:", "// sideboard", "// sb"}
    _MAIN_KEYWORDS = {"deck", "commander"}

    lines = text.splitlines()

    # Decide whether a blank line should act as main→side boundary.
    # Only use blank-line fallback when there is no explicit sideboard marker.
    has_explicit_side = any(
        l.strip().lower() in _SIDE_KEYWORDS
        or l.strip().lower().startswith("// sideboard")
        or l.strip().lower().startswith("sb:")
        for l in lines
    )

    main, side = {}, {}
    section = main
    blank_pending = False   # True after blank line (for fallback mode only)

    def _add(dest: dict, raw_name: str, qty: int):
        name = re.sub(r'\s+\(\w{2,5}\)\s+\d+.*$', '', raw_name).strip()
        if name:
            dest[name] = dest.get(name, 0) + qty

    for raw in lines:
        stripped = raw.strip()
        low = stripped.lower()

        # ── Blank line ────────────────────────────────────────────────
        if not stripped:
            if not has_explicit_side and section is main and main:
                blank_pending = True
            continue

        # ── Mainboard headers ─────────────────────────────────────────
        if low in _MAIN_KEYWORDS:
            section = main
            blank_pending = False
            continue

        # ── Sideboard headers (standalone line) ───────────────────────
        if (low in _SIDE_KEYWORDS
                or low.startswith("// sideboard")
                or low.startswith("// sb")):
            section = side
            blank_pending = False
            continue

        # ── Inline "SB: 4 Lightning Bolt" prefix ─────────────────────
        sb_inline = re.match(r'^(?:sb|sideboard):\s+(\d+)x?\s+(.+)',
                             stripped, re.IGNORECASE)
        if sb_inline:
            _add(side, sb_inline.group(2), int(sb_inline.group(1)))
            blank_pending = False
            continue

        # ── Regular card line ─────────────────────────────────────────
        m = re.match(r'^(\d+)x?\s+(.+)', stripped)
        if m:
            # Blank-line fallback: first card after a blank switches to side
            if blank_pending and section is main:
                section = side
            blank_pending = False
            _add(section, m.group(2), int(m.group(1)))

    return main, side


# ------------------------------------------------------------------
# URL import
# ------------------------------------------------------------------

def _fetch_decklist_from_url(url: str) -> str:
    """Fetch a decklist from a supported URL and return as Arena-format text.

    Supported: Moxfield, Archidekt, MTGGoldfish, MTGTop8.
    """
    import requests

    url = url.strip()

    # Moxfield: https://moxfield.com/decks/[id]
    if "moxfield.com/decks/" in url:
        deck_id = url.rstrip("/").split("/")[-1]
        api = f"https://api2.moxfield.com/v2/decks/all/{deck_id}"
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            resp = scraper.get(api, timeout=15)
        except ImportError:
            resp = requests.get(api, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        lines = ["Deck"]
        for name, card in data.get("mainboard", {}).items():
            lines.append(f"{card.get('quantity', 1)} {name}")
        if data.get("sideboard"):
            lines.append("")
            lines.append("Sideboard")
            for name, card in data.get("sideboard", {}).items():
                lines.append(f"{card.get('quantity', 1)} {name}")
        return "\n".join(lines)

    # MTGGoldfish: https://www.mtggoldfish.com/deck/[id]
    if "mtggoldfish.com/deck/" in url:
        deck_id = url.rstrip("/").split("/")[-1].split("#")[0]
        dl_url = f"https://www.mtggoldfish.com/deck/download/{deck_id}"
        resp = requests.get(dl_url, headers={"User-Agent": "MTGMetaAnalyzer/1.0"}, timeout=15)
        resp.raise_for_status()
        return resp.text.strip()

    # Archidekt: https://archidekt.com/decks/[id]
    if "archidekt.com/decks/" in url:
        deck_id = url.rstrip("/").split("/")[-1].split("#")[0]
        api = f"https://archidekt.com/api/decks/{deck_id}/small/"
        resp = requests.get(api, headers={"User-Agent": "MTGMetaAnalyzer/1.0"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        lines = ["Deck"]
        for card in data.get("cards", []):
            cat = card.get("categories", [""])
            name = card.get("card", {}).get("oracleCard", {}).get("name", "")
            qty = card.get("quantity", 1)
            if not name:
                continue
            if "Sideboard" in cat:
                continue  # collect sideboard in second pass
            lines.append(f"{qty} {name}")
        sb = [c for c in data.get("cards", []) if "Sideboard" in c.get("categories", [])]
        if sb:
            lines.append("")
            lines.append("Sideboard")
            for card in sb:
                name = card.get("card", {}).get("oracleCard", {}).get("name", "")
                qty = card.get("quantity", 1)
                if name:
                    lines.append(f"{qty} {name}")
        return "\n".join(lines)

    # MTGTop8: https://mtgtop8.com/event?e=[id]&d=[deck_id]
    if "mtgtop8.com" in url:
        # MTGTop8 has a MTGO download link: same URL with &d=[id]&f=MO
        # Parse the deck from the page's card list divs
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        lines = ["Deck"]
        in_side = False
        for div in soup.select("div.deck_line, div.deck_line_bot"):
            qty_span = div.select_one("span.deck_qty")
            name_span = div.select_one("span.deck_name") or div.select_one("a")
            if qty_span and name_span:
                qty = qty_span.text.strip()
                name = name_span.text.strip()
                if qty and name:
                    lines.append(f"{qty} {name}")
            elif "Sideboard" in div.text or "SB:" in div.text:
                in_side = True
                lines.append("")
                lines.append("Sideboard")
        if len(lines) > 1:
            return "\n".join(lines)
        # Fallback: try textarea
        textarea = soup.find("textarea")
        if textarea and textarea.text.strip():
            return textarea.text.strip()
        raise ValueError("Could not parse decklist from MTGTop8 page")

    raise ValueError(
        f"Unsupported URL. Supported: Moxfield, Archidekt, MTGGoldfish, MTGTop8"
    )


# ------------------------------------------------------------------
# Background worker
# ------------------------------------------------------------------

class _AnalyzeWorker(QThread):
    blunder_done = pyqtSignal(object)
    chapin_done  = pyqtSignal(object)
    error        = pyqtSignal(str)

    def __init__(self, mainboard, sideboard, format_name, archetype, parent=None):
        super().__init__(parent)
        self._main  = mainboard
        self._side  = sideboard
        self._fmt   = format_name
        self._arch  = archetype

    def run(self):
        try:
            from analysis.blunders import analyze_deck
            from analysis.chapin   import evaluate_deck
            blunder = analyze_deck(self._main, self._side, self._fmt, self._arch,
                                   check_legality=False)
            self.blunder_done.emit(blunder)
            chapin = evaluate_deck(self._main, self._side, self._fmt, self._arch)
            self.chapin_done.emit(chapin)
        except Exception as e:
            self.error.emit(str(e))


# ------------------------------------------------------------------
# Tab widget
# ------------------------------------------------------------------

_SEV_COLORS = {"Major": "#e6194b", "Moderate": "#f58231", "Minor": "#bfef45"}
_PRINCIPLES  = ["Threats", "Answers", "Consistency", "Velocity", "Mana", "Clock"]


def _card_reason(oracle_text: str | None, type_line: str | None, zone: str) -> str:
    """
    Derive a short explanation of why a card sees play in the given zone,
    using oracle text and type line heuristics.
    """
    text  = (oracle_text or "").lower()
    types = (type_line   or "").lower()
    parts = []

    # Sideboard-specific roles
    if zone == "Side":
        if any(k in text for k in ("exile", "remove")) and "graveyard" in text:
            parts.append("Graveyard hate — exiles cards from graveyards")
        if "counter target" in text:
            parts.append("Permission — counters specific threats")
        if "destroy target artifact" in text or "artifact" in types and "destroy" in text:
            parts.append("Artifact removal")
        if "destroy target enchantment" in text or "enchantment" in types and "destroy" in text:
            parts.append("Enchantment removal")
        if "life" in text and "gain" in text:
            parts.append("Life gain — stabilises against aggro")
        if "discard" in text:
            parts.append("Hand disruption — strips key combo/control pieces")

    # General roles
    if not parts or zone == "Main":
        if "counter target spell" in text:
            parts.append("Counterspell — answers non-creature threats")
        elif "counter target" in text:
            parts.append("Targeted counter magic")
        if "exile target" in text or ("exile" in text and "target creature" in text):
            parts.append("Exile removal — handles indestructible threats")
        elif "destroy target creature" in text or "destroy target permanent" in text:
            parts.append("Removal — clears blockers or key threats")
        elif "deals" in text and "damage" in text and "target" in text:
            parts.append("Burn — flexible damage to creature or player")
        if "draw" in text and "card" in text:
            parts.append("Card advantage")
        if "discard" in text and zone == "Main":
            parts.append("Hand disruption")
        if "lifelink" in text:
            parts.append("Provides life gain while pressuring")
        if "flash" in text:
            parts.append("Flash — can hold up interaction, deploy at end of turn")

    # Fallback by type
    if not parts:
        if "planeswalker" in types:
            parts.append("Planeswalker — generates value each turn")
        elif "creature" in types:
            parts.append("Alternate threat — some lists prefer this body")
        elif "land" in types:
            parts.append("Utility land — provides mana fixing or enters-play effect")
        elif "instant" in types or "sorcery" in types:
            parts.append("Situational spell — useful in specific matchups")
        elif "enchantment" in types:
            parts.append("Persistent effect — some lists run this for coverage")
        elif "artifact" in types:
            parts.append("Artifact utility — niche but recurs in some builds")
        else:
            parts.append("Flex pick — appears in some lists as a one- or two-of")

    return "; ".join(parts[:2])


class DeckAnalyzerTab(QWidget):
    def __init__(self, parent=None, on_simulate=None):
        """
        on_simulate: optional callable(deck_text: str, source_label: str).
        Wired by main_window to send the current decklist to SIMULATE.
        """
        super().__init__(parent)
        self._on_simulate = on_simulate
        self._worker  = None
        self._workers = []          # keep refs alive
        self._parsed_main = {}
        self._parsed_side = {}
        self._build_ui()
        self._refresh_archetypes()  # populate combo on first show

    def cleanup(self):
        """Stop running workers. Called by MainWindow on app exit."""
        if self._worker is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass
            self._worker = None
        for w in self._workers:
            try:
                w.blockSignals(True)
            except RuntimeError:
                pass
        self._workers.clear()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM, theme.SPACE_SM)
        layout.setSpacing(6)

        # ── Top controls ──────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(theme.SPACE_SM)

        ctrl.addWidget(QLabel("Format:"))
        self._fmt = QComboBox()
        self._fmt.addItems(["standard", "pioneer", "modern", "legacy"])
        self._fmt.setFixedWidth(120)
        self._fmt.currentIndexChanged.connect(self._refresh_archetypes)
        ctrl.addWidget(self._fmt)

        ctrl.addWidget(QLabel("Archetype:"))
        self._arch = QLineEdit()
        self._arch.setPlaceholderText("optional label, e.g. Izzet Prowess")
        self._arch.setFixedWidth(210)
        ctrl.addWidget(self._arch)

        self._analyze_btn = QPushButton("Analyze Deck")
        self._analyze_btn.setStyleSheet(theme.btn_primary())
        self._analyze_btn.clicked.connect(self._run)
        ctrl.addWidget(self._analyze_btn)

        self._legality_btn = QPushButton("Check Legality")
        self._legality_btn.setStyleSheet(theme.btn_secondary())
        self._legality_btn.setToolTip(
            "Verify decklist legality for this format.\n"
            "Checks: 60 main / 15 side, banned cards, card legality.\n"
            "Required at all RCQ events (Competitive REL)."
        )
        self._legality_btn.clicked.connect(self._run_legality_check)
        ctrl.addWidget(self._legality_btn)

        self._export_btn = QPushButton("Export ▾")
        self._export_btn.setStyleSheet(theme.btn_secondary())
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        ctrl.addWidget(self._export_btn)

        # Send the current paste area to SIMULATE tab for goldfish/matchup runs.
        # Only shown when main_window wired an on_simulate callback.
        if self._on_simulate is not None:
            self._simulate_btn = QPushButton("Simulate ▸")
            self._simulate_btn.setStyleSheet(theme.btn_secondary())
            self._simulate_btn.setToolTip(
                "Send this decklist to the SIMULATE tab "
                "(META > SIMULATE) with the paste area pre-filled."
            )
            self._simulate_btn.clicked.connect(self._on_send_to_simulate)
            ctrl.addWidget(self._simulate_btn)

        self._status = QLabel("")
        ctrl.addWidget(self._status)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── Load avg deck row ─────────────────────────────────────────
        load_row = QHBoxLayout()
        load_row.setSpacing(theme.SPACE_SM)

        lbl = QLabel("Load avg deck:")
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM};")
        load_row.addWidget(lbl)

        self._arch_combo = QComboBox()
        self._arch_combo.setEditable(True)
        self._arch_combo.setMinimumWidth(220)
        self._arch_combo.setPlaceholderText("Select archetype…")
        load_row.addWidget(self._arch_combo, 1)

        load_row.addWidget(QLabel("over"))
        self._load_weeks = QComboBox()
        for label, _ in theme.TIMEFRAME_OPTIONS:
            self._load_weeks.addItem(label)
        self._load_weeks.setCurrentText(theme.TIMEFRAME_DEFAULT)
        self._load_weeks.setFixedWidth(100)
        load_row.addWidget(self._load_weeks)

        self._load_btn = QPushButton("Load")
        self._load_btn.setStyleSheet(theme.btn_secondary())
        self._load_btn.setFixedHeight(26)
        self._load_btn.clicked.connect(self._load_avg_deck)
        load_row.addWidget(self._load_btn)

        load_row.addStretch()
        layout.addLayout(load_row)

        # ── Horizontal splitter: input | results ─────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: decklist input
        left = QFrame()
        lv   = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 4, 0)
        paste_row = QHBoxLayout()
        paste_row.addWidget(QLabel("Paste decklist (Arena export format):"))
        paste_row.addStretch()
        self._url_btn = QPushButton("Import from URL")
        self._url_btn.setStyleSheet(theme.btn_primary())
        self._url_btn.setToolTip("Import decklist from Moxfield, Archidekt, MTGGoldfish, or MTGTop8")
        self._url_btn.clicked.connect(self._import_from_url)
        paste_row.addWidget(self._url_btn)
        lv.addLayout(paste_row)
        self._deck_input = QPlainTextEdit()
        self._deck_input.setPlaceholderText(
            "Deck\n4 Lightning Bolt\n4 Monastery Swiftspear\n"
            "...\n\nSideboard\n2 Negate\n3 Mystical Dispute\n..."
        )
        self._deck_input.setFont(QFont("Consolas", 10))
        lv.addWidget(self._deck_input)

        # Recommendations panel — hidden until an avg deck is loaded
        self._rec_box = QGroupBox("Flex / Tech Recommendations")
        self._rec_box.setVisible(False)
        rv2 = QVBoxLayout(self._rec_box)
        rv2.setContentsMargins(4, 4, 4, 4)
        rv2.setSpacing(2)
        self._rec_lbl = QLabel("")
        self._rec_lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        rv2.addWidget(self._rec_lbl)
        self._rec_table = QTableWidget(0, 3)
        self._rec_table.setHorizontalHeaderLabels(["Card", "Zone", "Incl %"])
        self._rec_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._rec_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._rec_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._rec_table.setColumnWidth(1, 50)
        self._rec_table.setColumnWidth(2, 60)
        self._rec_table.setToolTip("Hover a card row to see why it sees play")
        self._rec_table.verticalHeader().setVisible(False)
        self._rec_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._rec_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._rec_table.setMaximumHeight(160)
        self._rec_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        from gui.widgets.card_tooltip import install_card_tooltip
        install_card_tooltip(self._rec_table, card_name_column=0)
        rv2.addWidget(self._rec_table)
        lv.addWidget(self._rec_box)

        splitter.addWidget(left)

        # Right: results
        right = QFrame()
        rv    = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(theme.SPACE_SM)

        # Blunder section
        blunder_hdr = QLabel("Blunder Detection")
        blunder_hdr.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        rv.addWidget(blunder_hdr)

        self._blunder_table = QTableWidget(0, 3)
        self._blunder_table.setHorizontalHeaderLabels(["Severity", "Category", "Issue"])
        self._blunder_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._blunder_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._blunder_table.setAlternatingRowColors(True)
        self._blunder_table.verticalHeader().setVisible(False)
        self._blunder_table.setMaximumHeight(200)
        rv.addWidget(self._blunder_table)

        self._score_lbl = QLabel("\u2014")
        rv.addWidget(self._score_lbl)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        rv.addWidget(div)

        # Chapin section
        chapin_hdr = QLabel("Chapin Principles")
        chapin_hdr.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        rv.addWidget(chapin_hdr)

        self._chapin_bars: dict = {}
        for p in _PRINCIPLES:
            row_layout = QHBoxLayout()
            lbl = QLabel(f"{p}:")
            lbl.setFixedWidth(92)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("")          # we'll show score in the separate label
            score_lbl = QLabel("\u2014")
            score_lbl.setFixedWidth(36)
            score_lbl.setAlignment(Qt.AlignmentFlag.AlignRight |
                                   Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(lbl)
            row_layout.addWidget(bar, 1)
            row_layout.addWidget(score_lbl)
            rv.addLayout(row_layout)
            self._chapin_bars[p] = (lbl, bar, score_lbl)

        self._overall_lbl = QLabel("")
        self._overall_lbl.setWordWrap(True)
        rv.addWidget(self._overall_lbl)

        # Deck similarity section
        self._sim_lbl = QLabel("")
        self._sim_lbl.setWordWrap(True)
        self._sim_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 10px;")
        rv.addWidget(self._sim_lbl)

        self._similar_decks_lbl = QLabel("")
        self._similar_decks_lbl.setWordWrap(True)
        self._similar_decks_lbl.setTextFormat(Qt.TextFormat.RichText)
        self._similar_decks_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 10px;"
        )
        # Intercept the 'deck:{id}' anchor hrefs we render in the rows.
        self._similar_decks_lbl.setOpenExternalLinks(False)
        self._similar_decks_lbl.linkActivated.connect(self._on_similar_deck_link)
        self._similar_deck_cache = {}
        rv.addWidget(self._similar_decks_lbl)

        # Baseline vs deviation section
        self._baseline_lbl = QLabel("")
        self._baseline_lbl.setWordWrap(True)
        self._baseline_lbl.setStyleSheet(f"color: {theme.TEXT}; font-size: 10px;")
        rv.addWidget(self._baseline_lbl)

        # Divider
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        rv.addWidget(div2)

        # Legality checker section
        legality_hdr_row = QHBoxLayout()
        legality_hdr = QLabel("Decklist Legality")
        legality_hdr.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        legality_hdr_row.addWidget(legality_hdr)
        legality_hdr_row.addStretch()
        rel_lbl = QLabel("Competitive REL — decklists required at RCQs")
        rel_lbl.setStyleSheet(
            f"color: #f58231; font-size: 10px; "
            f"border: 1px solid #f58231; border-radius: 3px; padding: 1px 5px;"
        )
        rel_lbl.setToolTip(
            "All RCQ events run at Competitive Rules Enforcement Level.\n"
            "Decklists are mandatory. Errors result in a Game Loss.\n"
            "Use 'Check Legality' before submitting your decklist."
        )
        legality_hdr_row.addWidget(rel_lbl)
        rv.addLayout(legality_hdr_row)

        self._legality_summary = QLabel("Click 'Check Legality' to verify your decklist.")
        self._legality_summary.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self._legality_summary.setWordWrap(True)
        rv.addWidget(self._legality_summary)

        self._legality_table = QTableWidget(0, 4)
        self._legality_table.setHorizontalHeaderLabels(["Card", "Zone", "Qty", "Issue"])
        self._legality_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for i in (1, 2, 3):
            self._legality_table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents
            )
        self._legality_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._legality_table.setAlternatingRowColors(True)
        self._legality_table.verticalHeader().setVisible(False)
        self._legality_table.setVisible(False)
        self._legality_table.setMaximumHeight(150)
        rv.addWidget(self._legality_table)

        # Divider
        div3 = QFrame()
        div3.setFrameShape(QFrame.Shape.HLine)
        rv.addWidget(div3)

        # Hypergeometric calculator
        hyper_hdr = QLabel("Hypergeometric Calculator")
        hyper_hdr.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        rv.addWidget(hyper_hdr)

        hyper_row1 = QHBoxLayout()
        for label, attr, default in [
            ("Deck size",    "_hyper_deck",  "60"),
            ("Copies",       "_hyper_copies","4"),
            ("Cards drawn",  "_hyper_drawn", "7"),
            ("Want ≥",       "_hyper_want",  "1"),
        ]:
            hyper_row1.addWidget(QLabel(f"{label}:"))
            field = QLineEdit(default)
            field.setFixedWidth(44)
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.textChanged.connect(self._calc_hypergeom)
            setattr(self, attr, field)
            hyper_row1.addWidget(field)
        rv.addLayout(hyper_row1)

        self._hyper_result = QLabel("")
        self._hyper_result.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 13px; font-weight: bold; padding: 2px 0;"
        )
        rv.addWidget(self._hyper_result)
        self._calc_hypergeom()   # show initial result

        rv.addStretch()

        splitter.addWidget(right)
        splitter.setSizes([360, 460])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Load average deck from DB
    # ------------------------------------------------------------------

    def _refresh_archetypes(self):
        """Populate the archetype combo with top archetypes for current format."""
        fmt = self._fmt.currentText()

        def _do():
            from db.database import get_combined_connection
            conn = get_combined_connection()
            try:
                rows = conn.execute("""
                    SELECT d.archetype, COUNT(*) AS cnt
                    FROM decks d
                    JOIN events e ON e.id = d.event_id
                    WHERE lower(e.format) = lower(?)
                    GROUP BY d.archetype
                    ORDER BY cnt DESC
                    LIMIT 120
                """, [fmt]).fetchall()
            finally:
                conn.close()
            return [r[0] for r in rows]

        w = DataLoadWorker(_do)
        w.result.connect(self._on_archetypes_loaded)
        w.start()
        self._workers.append(w)

    def _on_archetypes_loaded(self, archetypes: list):
        current = self._arch_combo.currentText()
        self._arch_combo.blockSignals(True)
        self._arch_combo.clear()
        self._arch_combo.addItems(archetypes)
        # Restore previous selection if still present
        idx = self._arch_combo.findText(current)
        if idx >= 0:
            self._arch_combo.setCurrentIndex(idx)
        else:
            self._arch_combo.setCurrentIndex(-1)
        self._arch_combo.blockSignals(False)

    def _load_avg_deck(self):
        arch = self._arch_combo.currentText().strip()
        if not arch:
            self._status.setText("Select an archetype first.")
            return

        fmt   = self._fmt.currentText()
        weeks = theme.TIMEFRAME_OPTIONS[self._load_weeks.currentIndex()][1]
        since_dt = (datetime.now() - timedelta(weeks=weeks)) if weeks is not None else None

        self._load_btn.setEnabled(False)
        self._status.setText(f"Loading {arch}…")

        from gui.widgets.archetype_detail import _load_archetype_data
        w = DataLoadWorker(_load_archetype_data, {
            "archetype": arch,
            "format_name": fmt,
            "since_dt": since_dt,
        })
        w.result.connect(self._on_avg_deck_loaded)
        w.error.connect(lambda e: (
            self._status.setText(theme.friendly_error(e)),
            self._load_btn.setEnabled(True),
        ))
        w.finished.connect(lambda: self._load_btn.setEnabled(True))
        w.start()
        self._workers.append(w)

    def _on_avg_deck_loaded(self, data):
        if not data:
            self._status.setText("No decklists found for that archetype/timeframe.")
            return

        # Build Arena-format text from average deck.
        # Use avg_qty * inclusion_rate to get the expected copies per deck;
        # skip cards that round to 0 (low-inclusion flex cards).
        def _expected_qty(card):
            return round(card["avg_qty"] * card.get("inclusion_rate", 1.0))

        lines = ["Deck"]
        for card in data["mainboard"]:
            qty = _expected_qty(card)
            if qty > 0:
                lines.append(f"{qty} {card['name']}")
        if data["sideboard"]:
            lines.append("")
            lines.append("Sideboard")
            for card in data["sideboard"]:
                qty = _expected_qty(card)
                if qty > 0:
                    lines.append(f"{qty} {card['name']}")

        self._deck_input.setPlainText("\n".join(lines))
        self._arch.setText(data["archetype"])

        total_main = sum(_expected_qty(c) for c in data["mainboard"] if _expected_qty(c) > 0)
        total_side = sum(_expected_qty(c) for c in data["sideboard"] if _expected_qty(c) > 0)
        self._status.setText(
            f"Loaded {data['archetype']} avg ({data['deck_count']} decks — "
            f"{total_main} main / {total_side} side)"
        )

        # Populate recommendations: cards excluded from the deck (rounded to 0)
        # that still have ≥10% inclusion — sorted by inclusion rate descending.
        recs_main = [(c, "Main") for c in data["mainboard"] if _expected_qty(c) == 0]
        recs_side = [(c, "Side") for c in data["sideboard"] if _expected_qty(c) == 0]
        recs = recs_main + recs_side
        recs.sort(key=lambda t: -t[0].get("inclusion_rate", 0))

        if recs:
            # Batch-fetch oracle text + type for all recommended cards
            from db.database import get_combined_connection
            names = [c["name"] for c, _ in recs]
            placeholders = ",".join("?" * len(names))
            conn = get_combined_connection()
            try:
                rows = conn.execute(
                    f"SELECT name, oracle_text, type_line FROM card_data "
                    f"WHERE name IN ({placeholders})",
                    names,
                ).fetchall()
            finally:
                conn.close()
            card_info = {r["name"]: r for r in rows}

            self._rec_box.setVisible(True)
            self._rec_lbl.setText(
                f"{len(recs)} flex/tech cards appear in some {data['archetype']} lists "
                f"but aren't consistent enough for the average deck:"
            )
            self._rec_table.setRowCount(len(recs))
            for row, (card, zone) in enumerate(recs):
                inc  = card.get("inclusion_rate", 0)
                info = card_info.get(card["name"])
                why  = _card_reason(
                    (info["oracle_text"] if info else None),
                    (info["type_line"]   if info else None),
                    zone,
                )
                name_i = QTableWidgetItem(card["name"])
                zone_i = QTableWidgetItem(zone)
                zone_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                inc_i  = QTableWidgetItem(f"{inc*100:.0f}%")
                inc_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Tint rows by inclusion strength
                if inc >= 0.40:
                    tint = QColor(30, 55, 35)
                elif inc >= 0.25:
                    tint = QColor(45, 45, 20)
                else:
                    tint = QColor(50, 35, 20)
                tooltip = f"Recommended: {zone}\n\n{why}"
                for item in (name_i, zone_i, inc_i):
                    item.setBackground(tint)
                    item.setToolTip(tooltip)
                self._rec_table.setItem(row, 0, name_i)
                self._rec_table.setItem(row, 1, zone_i)
                self._rec_table.setItem(row, 2, inc_i)
        else:
            self._rec_box.setVisible(False)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _calc_hypergeom(self):
        """Compute P(drawing >= want copies) from a hypergeometric distribution."""
        try:
            N = int(self._hyper_deck.text())
            K = int(self._hyper_copies.text())
            n = int(self._hyper_drawn.text())
            k = int(self._hyper_want.text())
            if not (0 < N <= 250 and 0 <= K <= N and 0 <= n <= N and 0 <= k <= min(K, n)):
                raise ValueError
        except (ValueError, AttributeError):
            self._hyper_result.setText("—")
            return

        try:
            from scipy.stats import hypergeom
            prob = hypergeom.sf(k - 1, N, K, n)
        except ImportError:
            # Manual calculation without scipy
            def _comb(a, b):
                if b < 0 or b > a:
                    return 0
                import math
                return math.comb(a, b)
            total = _comb(N, n)
            if total == 0:
                self._hyper_result.setText("—")
                return
            prob = sum(
                _comb(K, i) * _comb(N - K, n - i)
                for i in range(k, min(K, n) + 1)
            ) / total

        pct = prob * 100
        color = theme.OK if pct >= 60 else (theme.WARN if pct >= 30 else theme.ERR)
        self._hyper_result.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: bold; padding: 2px 0;"
        )
        self._hyper_result.setText(
            f"P(≥{k} in {n} draws)  =  {pct:.1f}%"
        )

    def _import_from_url(self):
        """Import decklist from a URL (Moxfield, Archidekt, MTGGoldfish, MTGTop8)."""
        from PyQt6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(
            self, "Import from URL",
            "Paste a deck URL (Moxfield, Archidekt, MTGGoldfish, MTGTop8):",
        )
        if not ok or not url.strip():
            return
        url = url.strip()
        self._status.setText("Fetching decklist\u2026")
        self._url_btn.setEnabled(False)

        def _do():
            return _fetch_decklist_from_url(url)

        w = DataLoadWorker(_do)
        w.result.connect(self._on_url_imported)
        w.error.connect(lambda e: (
            self._status.setText(f"Import failed: {e}"),
            self._url_btn.setEnabled(True),
        ))
        w.finished.connect(lambda: self._url_btn.setEnabled(True))
        w.finished.connect(w.deleteLater)
        w.start()
        self._workers.append(w)

    def _on_url_imported(self, text: str):
        if text:
            self._deck_input.setPlainText(text)
            self._status.setText("Decklist imported from URL.")
        else:
            self._status.setText("No decklist found at that URL.")

    def _on_export(self):
        from gui.widgets.deck_export import show_export_menu
        arch = self._arch.text().strip() or "Pasted Deck"
        show_export_menu(
            self._export_btn,
            self._parsed_main,
            self._parsed_side,
            arch,
            self._fmt.currentText(),
        )

    def _on_send_to_simulate(self):
        """Hand the current paste-area deck text to SIMULATE."""
        text = self._deck_input.toPlainText().strip()
        if not text:
            self._status.setText("Paste a decklist first.")
            return
        # Source label: try to read the archetype field if it's present; works
        # whether _arch is a QComboBox (currentText) or QLineEdit (text).
        arch = ""
        if hasattr(self, "_arch"):
            getter = getattr(self._arch, "currentText", None) or getattr(self._arch, "text", None)
            if getter:
                arch = (getter() or "").strip()
        source = arch if arch and arch not in ("(auto-detect)", "") else "Deck Analyzer paste"
        if self._on_simulate is not None:
            self._on_simulate(text, source, format_hint=self._fmt.currentText())

    def _run(self):
        text = self._deck_input.toPlainText().strip()
        if not text:
            self._status.setText("Paste a decklist first.")
            return
        main, side = parse_arena_decklist(text)
        if not main:
            self._status.setText("Could not parse decklist — use Arena export format.")
            return

        self._parsed_main = main
        self._parsed_side = side
        self._export_btn.setEnabled(True)

        fmt  = self._fmt.currentText()
        arch = self._arch.text().strip() or "Pasted Deck"
        total = sum(main.values())
        self._status.setText(f"Analyzing {total} cards\u2026")
        self._analyze_btn.setEnabled(False)
        self._clear_results()

        # Cancel any previous analysis still running
        if getattr(self, "_worker", None) is not None:
            try:
                self._worker.blockSignals(True)
            except RuntimeError:
                pass
            self._worker = None

        self._worker = _AnalyzeWorker(main, side, fmt, arch)
        self._worker.blunder_done.connect(self._show_blunder)
        self._worker.chapin_done.connect(self._show_chapin)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(lambda: self._analyze_btn.setEnabled(True))
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.finished.connect(lambda: self._run_deck_similarity(main, fmt))
        self._worker.finished.connect(lambda: self._run_similar_scraped(main, fmt))
        self._worker.finished.connect(lambda: self._run_auto_classify(main, fmt))
        self._worker.finished.connect(lambda: self._run_baseline(main, side, fmt, arch))
        self._worker.start()

    def _clear_results(self):
        self._blunder_table.setRowCount(0)
        self._score_lbl.setText("\u2014")
        self._overall_lbl.setText("")
        self._sim_lbl.setText("")
        self._similar_decks_lbl.setText("")
        self._baseline_lbl.setText("")
        for lbl, bar, score_lbl in self._chapin_bars.values():
            bar.setValue(0)
            score_lbl.setText("\u2014")
            lbl.setToolTip("")
            bar.setToolTip("")
            score_lbl.setToolTip("")

    def _show_blunder(self, report):
        issues = getattr(report, "issues", [])
        self._blunder_table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            sev  = getattr(issue, "severity", "")
            cat  = getattr(issue, "category", "")
            desc = getattr(issue, "description", "")

            sev_item = QTableWidgetItem(sev)
            color    = _SEV_COLORS.get(sev, "#aaaaaa")
            sev_item.setForeground(QColor(color))
            sev_item.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            self._blunder_table.setItem(row, 0, sev_item)
            self._blunder_table.setItem(row, 1, QTableWidgetItem(cat))
            self._blunder_table.setItem(row, 2, QTableWidgetItem(desc))

        score   = getattr(report, "blunder_score",        0)
        quality = getattr(report, "construction_quality", "")
        main_ct = getattr(report, "mainboard_count",      0)
        side_ct = getattr(report, "sideboard_count",      0)
        self._score_lbl.setText(
            f"Score: {score} pts  |  Quality: {quality}  |  "
            f"{main_ct} main / {side_ct} side"
        )
        self._status.setText("Blunder analysis complete.")

    def _show_chapin(self, report):
        for ps in getattr(report, "scores", []):
            name        = getattr(ps, "name",        "")
            score       = getattr(ps, "score",       0.0)
            explanation = getattr(ps, "explanation", "")
            if name in self._chapin_bars:
                lbl, bar, score_lbl = self._chapin_bars[name]
                bar.setValue(int(score * 10))
                score_lbl.setText(f"{score:.1f}")
                if explanation:
                    tip = f"{name} ({score:.1f}/10)\n\n{explanation}"
                    lbl.setToolTip(tip)
                    bar.setToolTip(tip)
                    score_lbl.setToolTip(tip)

        overall = getattr(report, "overall_score",   0.0)
        rating  = getattr(report, "overall_rating",  "")
        rec     = getattr(report, "recommendation",  "")
        self._overall_lbl.setText(
            f"Overall: {overall:.1f}/10  [{rating}]\n{rec}"
        )
        self._status.setText("Analysis complete.")

    def _on_error(self, msg):
        self._status.setText(theme.friendly_error(msg))
        self._analyze_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # Deck similarity (card embeddings)
    # ------------------------------------------------------------------

    def _run_deck_similarity(self, card_list: dict, format_name: str):
        """Find which meta archetypes the pasted deck is most similar to."""
        try:
            from analysis.card_embeddings import is_available, find_closest_archetype
            if not is_available():
                self._sim_lbl.setText("")
                return

            from gui.worker_threads import DataLoadWorker
            def _do():
                return find_closest_archetype(card_list, format_name, top_n=5)

            w = DataLoadWorker(_do)
            def _done(results):
                if not results:
                    self._sim_lbl.setText("")
                    return
                lines = ["Deck Similarity (vs meta archetypes):"]
                for r in results:
                    pct = r["similarity"] * 100
                    lines.append(f"  {r['archetype']:30s} {pct:.0f}%")
                self._sim_lbl.setText("\n".join(lines))
            w.result.connect(_done)
            w.error.connect(lambda _: self._sim_lbl.setText(""))
            w.finished.connect(w.deleteLater)
            w.start()
            # Keep reference to prevent GC
            self._sim_worker = w
        except Exception:
            self._sim_lbl.setText("")

    def _on_similar_deck_link(self, href: str):
        """Open the Deck Detail dialog for a 'deck:{id}' href from the
        similar-scraped-decks panel."""
        if not href.startswith("deck:"):
            return
        try:
            deck_id = int(href[5:])
        except ValueError:
            return
        r = self._similar_deck_cache.get(deck_id)
        if not r:
            return
        from gui.tabs.search import _DeckDetailDialog
        dlg = _DeckDetailDialog(
            deck_id=deck_id,
            archetype=r.get("archetype", ""),
            player=r.get("player", ""),
            placement=r.get("placement"),
            event=r.get("event_name", ""),
            date=r.get("date", ""),
            fmt=self._fmt.currentText(),
            parent=self,
            on_simulate=self._on_simulate,
        )
        dlg.exec()

    def _run_similar_scraped(self, card_list: dict, format_name: str):
        """Find the top 5 scraped decks most similar to the pasted list."""
        try:
            from gui.worker_threads import DataLoadWorker

            def _do():
                from analysis.deck_analysis import find_similar_scraped_decks
                return find_similar_scraped_decks(
                    card_list, format_name, top_n=5
                )

            w = DataLoadWorker(_do)

            def _done(results):
                if not results:
                    self._similar_decks_lbl.setText("")
                    return
                rows = [
                    "<b>Similar scraped decks (by card overlap):</b>",
                    "<table cellpadding='2' style='font-family:Consolas,monospace;'>",
                    "<tr style='color:#888'>"
                    "<td>Sim</td><td>Archetype</td><td>Player</td>"
                    "<td>Finish</td><td>Event</td><td>Date</td></tr>",
                ]
                # Cache metadata so the linkActivated handler can open the
                # right deck without a second DB hit.
                self._similar_deck_cache = {r["deck_id"]: r for r in results}
                for r in results:
                    pct = r["similarity"] * 100
                    place = (f"#{r['placement']}" if r["placement"]
                             else "-")
                    event = (r["event_name"] or "")[:36]
                    link = f"deck:{r['deck_id']}"
                    rows.append(
                        f"<tr>"
                        f"<td>{pct:.0f}%</td>"
                        f"<td><a href='{link}' style='color:{theme.ACCENT};"
                        f"text-decoration:none;'>{r['archetype']}</a></td>"
                        f"<td>{r['player']}</td>"
                        f"<td>{place}</td>"
                        f"<td>{event}</td>"
                        f"<td>{r['date']}</td>"
                        f"</tr>"
                    )
                rows.append("</table>")
                rows.append(
                    f"<span style='color:{theme.TEXT_DIM}; font-size:10px;'>"
                    "Click an archetype name to open that deck's full list."
                    "</span>"
                )
                self._similar_decks_lbl.setText("".join(rows))

            w.result.connect(_done)
            w.error.connect(lambda _: self._similar_decks_lbl.setText(""))
            w.finished.connect(w.deleteLater)
            w.start()
            self._similar_scraped_worker = w
        except Exception:
            self._similar_decks_lbl.setText("")

    # ------------------------------------------------------------------
    # Baseline vs deviation — compare user's list to average
    # ------------------------------------------------------------------

    def _run_baseline(self, main: dict, side: dict, fmt: str, arch: str):
        """Compare the pasted decklist against the average for its archetype."""
        if arch == "Pasted Deck":
            # Use auto-classified archetype if available
            arch = getattr(self, "_classified_arch", arch)
        if not arch or arch == "Pasted Deck":
            return
        try:
            def _do():
                from analysis.deck_analysis import compare_deck_to_average
                return compare_deck_to_average(
                    {"mainboard": main, "sideboard": side},
                    arch, fmt, min_inclusion=0.15,
                )

            w = DataLoadWorker(_do)

            def _done(result):
                if not result:
                    self._baseline_lbl.setText("")
                    return
                lines = [f"Baseline Comparison vs Average {arch}:"]
                mb = result.get("mainboard", {})
                added = mb.get("added", [])
                cut = mb.get("cut", [])
                adjusted = mb.get("adjusted", [])
                sim = result.get("similarity_score", 0)
                lines.append(f"  Similarity: {sim*100:.0f}%")
                if added:
                    lines.append(f"  You run (others don't): "
                                 + ", ".join(f"{c['name']} x{c['qty']}" for c in added[:5]))
                if cut:
                    lines.append(f"  You're missing (most run): "
                                 + ", ".join(f"{c['name']} ({c['inclusion_rate']*100:.0f}%)" for c in cut[:5]))
                if adjusted:
                    diffs = [f"{c['name']} ({c['diff']:+d})" for c in adjusted[:5]]
                    lines.append(f"  Qty differences: " + ", ".join(diffs))
                self._baseline_lbl.setText("\n".join(lines))

            w.result.connect(_done)
            w.error.connect(lambda _: self._baseline_lbl.setText(""))
            w.finished.connect(w.deleteLater)
            w.start()
            self._baseline_worker = w
        except Exception:
            self._baseline_lbl.setText("")

    # ------------------------------------------------------------------
    # Auto-classify archetype (KNN)
    # ------------------------------------------------------------------

    def _run_auto_classify(self, card_list: dict, format_name: str):
        """Auto-detect archetype and fill the label if empty."""
        if self._arch.text().strip():
            return  # user already provided a label

        try:
            from analysis.knn_classifier import hybrid_classify
            from gui.worker_threads import DataLoadWorker

            def _do():
                return hybrid_classify(card_list, format_name, min_confidence=0.5)

            w = DataLoadWorker(_do)
            def _done(result):
                if result and not self._arch.text().strip():
                    self._arch.setText(result)
                    self._arch.setStyleSheet(
                        f"color: {theme.ACCENT}; font-style: italic;"
                    )
            w.result.connect(_done)
            w.error.connect(lambda _: None)
            w.finished.connect(w.deleteLater)
            w.start()
            self._classify_worker = w
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Legality checker
    # ------------------------------------------------------------------

    def _run_legality_check(self):
        text = self._deck_input.toPlainText().strip()
        if not text:
            self._legality_summary.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: 11px;"
            )
            self._legality_summary.setText("Paste a decklist first.")
            return

        main, side = parse_arena_decklist(text)
        if not main:
            self._legality_summary.setStyleSheet(
                f"color: {theme.TEXT_DIM}; font-size: 11px;"
            )
            self._legality_summary.setText(
                "Could not parse decklist — use Arena export format."
            )
            return

        fmt = self._fmt.currentText()
        self._legality_btn.setEnabled(False)
        self._legality_summary.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 11px;"
        )
        self._legality_summary.setText("Checking legality…")
        self._legality_table.setVisible(False)

        def _do(main, side, fmt):
            import json
            from db.database import get_combined_connection

            all_cards = [(name, qty, "Main") for name, qty in main.items()]
            all_cards += [(name, qty, "Side") for name, qty in side.items()]

            names = [c[0] for c in all_cards]
            placeholders = ",".join("?" * len(names))

            conn = get_combined_connection()
            try:
                rows = conn.execute(
                    f"SELECT name, legalities FROM card_data "
                    f"WHERE name IN ({placeholders})",
                    names,
                ).fetchall()
            finally:
                conn.close()

            legality_map = {}
            for row in rows:
                try:
                    legality_map[row["name"]] = json.loads(row["legalities"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    legality_map[row["name"]] = {}

            # For cards not in DB, fall back to Scryfall
            missing = [n for n in names if n not in legality_map]
            for name in missing:
                try:
                    from scrapers.scryfall import get_card_data
                    card = get_card_data(name)
                    legality_map[name] = card.get("legalities", {}) if card else {}
                except Exception:
                    legality_map[name] = {}

            issues = []

            # Size checks
            main_count = sum(main.values())
            side_count = sum(side.values())
            if main_count != 60:
                issues.append({
                    "card": f"Mainboard total",
                    "zone": "Main",
                    "qty": main_count,
                    "issue": f"Must be exactly 60 cards (have {main_count})",
                })
            if side and side_count != 15:
                issues.append({
                    "card": "Sideboard total",
                    "zone": "Side",
                    "qty": side_count,
                    "issue": f"Must be exactly 15 cards (have {side_count})",
                })

            # Legality checks
            _BAD = {"banned", "not_legal", "restricted"}
            for name, qty, zone in all_cards:
                status = legality_map.get(name, {}).get(fmt, "unknown").lower()
                if status in _BAD:
                    label = status.replace("_", " ").title()
                    issues.append({
                        "card": name,
                        "zone": zone,
                        "qty": qty,
                        "issue": f"{label} in {fmt}",
                    })

            return {
                "issues": issues,
                "main_count": main_count,
                "side_count": side_count,
                "fmt": fmt,
            }

        w = DataLoadWorker(_do, {"main": main, "side": side, "fmt": fmt})
        w.result.connect(self._show_legality)
        w.error.connect(lambda e: (
            self._legality_summary.setText(theme.friendly_error(e)),
            self._legality_btn.setEnabled(True),
        ))
        w.finished.connect(lambda: self._legality_btn.setEnabled(True))
        w.start()
        self._workers.append(w)

    def _show_legality(self, result):
        issues     = result["issues"]
        main_count = result["main_count"]
        side_count = result["side_count"]
        fmt        = result["fmt"]

        if not issues:
            self._legality_summary.setStyleSheet(
                "color: #3cb44b; font-size: 11px; font-weight: bold;"
            )
            self._legality_summary.setText(
                f"\u2713 Legal \u2014 {main_count} main / {side_count} side, "
                f"no issues found for {fmt}."
            )
            self._legality_table.setVisible(False)
            return

        n = len(issues)
        self._legality_summary.setStyleSheet(
            "color: #e6194b; font-size: 11px; font-weight: bold;"
        )
        self._legality_summary.setText(
            f"\u2717 {n} issue{'s' if n != 1 else ''} found \u2014 "
            f"review before submitting your decklist."
        )

        self._legality_table.setRowCount(n)
        for row, issue in enumerate(issues):
            card_i = QTableWidgetItem(issue["card"])
            zone_i = QTableWidgetItem(issue["zone"])
            zone_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            qty_i  = QTableWidgetItem(str(issue["qty"]))
            qty_i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            issue_text = issue["issue"]
            issue_i = QTableWidgetItem(issue_text)
            lower = issue_text.lower()
            if "banned" in lower:
                issue_i.setForeground(QColor("#e6194b"))
            elif "restricted" in lower:
                issue_i.setForeground(QColor("#f58231"))
            elif "not legal" in lower:
                issue_i.setForeground(QColor("#f58231"))
            else:
                issue_i.setForeground(QColor("#bfef45"))

            self._legality_table.setItem(row, 0, card_i)
            self._legality_table.setItem(row, 1, zone_i)
            self._legality_table.setItem(row, 2, qty_i)
            self._legality_table.setItem(row, 3, issue_i)

        self._legality_table.setVisible(True)
