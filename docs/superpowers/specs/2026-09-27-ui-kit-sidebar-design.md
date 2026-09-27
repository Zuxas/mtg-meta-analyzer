# UI kit + sidebar nav: design (2026-09-27)

Branch: `ui/polish-kit`. The worktree is `E:\vscode ai project\_worktrees\analyzer-ui`, cut from `main` @ f4de5ed.

## Why
Jermey wants the analyzer to feel as clean and friendly as the MyMTGO desktop app. We studied that app's source; its licence allows reading and studying but not copying code. These are the UI principles we took from it:

- **Colour:** neutral surfaces plus one accent. Win and loss green/red are the only other saturated colours.
- **Consistency:** a small set of size, radius and type tokens, applied everywhere.
- **Reusable pieces:** a small domain component kit (stat cards, win-rate bar, record pill, segmented control, toasts).
- **Navigation:** a noun-based left sidebar.
- **Feedback:** non-blocking notifications instead of OK-only dialogs.

## Audit of `main` that motivated this
- 492 inline `setStyleSheet()` calls in tabs and widgets.
- 319 hardcoded hex colours (87 distinct). The top three are a 20-colour palette hard-coded outside theme.py.
- 13 distinct raw `font-size` px values.
- 69 `QMessageBox` uses, 22 of which are OK-only `information` pop-ups.
- 8 top-level tabs, several holding a nested tab row (tab-in-tab).

## What changed
1. **`gui/theme.py`** (additive only, no existing token changed):
   - `FONT_XS..FONT_HERO`, `RADIUS_SM/RADIUS/RADIUS_LG`
   - `WIN/LOSS/DRAW` and their `_BG` variants, `ACCENT_BG`, `SIDEBAR_W/ITEM_H`
   - `kit_stylesheet()`, appended by `apply_theme()`. Every rule is scoped by objectName or the `kit` dynamic property, so opted-out widgets look exactly as before.
2. **`gui/widgets/kit.py`**, new:
   - StatCard, KpiStrip, WinRateBar (fades below LOW_N_THRESHOLD, same rule as the GR-8 heatmap), RecordPill, SegmentedControl
   - Toast and a per-window toast host: bottom-right, stacks, at most 4 live, fades out, re-anchors on resize
   - `toast_info()`
3. **`gui/widgets/sidebar_tabbar.py`**, new:
   - `SidebarTabBar` plus `install_sidebar(tabs)`.
   - The root QTabWidget becomes a left sidebar with a Phosphor icon (qtawesome, already a dependency) and a Title-case label.
   - `tabText()` is untouched, so the command palette, tab-path persistence, Basic/Pro disclosure and the jump-to-SIMULATE callbacks all keep working unchanged.
4. **`gui/main_window.py`:** one call, `install_sidebar(self._tabs)`, replaces `setTabPosition(North)`.
5. **`gui/widgets/summary_bar.py`:** same public API. The title renders as an accent chip and each stat as its own chip. `_stats` is kept as a compatibility property (`tests/test_dashboard_summary_bar.py` reads it).
6. **`QMessageBox.information(` → `toast_info(`** in 9 files (20 calls). The shim keeps the modal dialog when:
   - the text is longer than 180 characters or 3 lines;
   - extra button arguments are passed;
   - there is no visible window.

   So behaviour can only get lighter, never lose information. The `tournament_prep.py` help buttons are deliberately left as dialogs.
7. **`scripts/ui_kit_gallery.py`:** a live preview, or `--png` for an offscreen render. It touches no database.
8. **`tests/test_ui_kit.py`:** 12 offscreen tests.

## Not in this change (next waves)
- **Wave 2:** a KPI strip and matchup-spread card on DASHBOARD and MATCH LOG, fed from match_log.
- **Wave 3:** migrate the hard-coded palette and raw font sizes to tokens, with a style-debt ratchet test so the counts can only go down.
- **Wave 4:** convert the remaining OK-only warnings to toasts where safe, and add SegmentedControl to the format and timeframe pickers.

## Verification
- `pytest` passes, the full suite plus the new kit tests.
- The gallery PNG renders.
- A launch smoke test of the real app against a copy of the DB. The live DB is never opened by this work.
