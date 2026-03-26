@echo off
REM ============================================================
REM  MTG Meta Analyzer - Background Database Fill
REM  Scrapes Standard, Pioneer, and Modern from MTGTop8 and
REM  MTGDecks, enriches cards, normalizes archetypes.
REM
REM  Runs minimized when double-clicked.
REM  Called by Windows Task Scheduler daily at 6:00 AM.
REM  All output logged to logs\background_fill.log
REM ============================================================

REM Self-minimize on double-click (Task Scheduler already runs hidden)
if "%~1"=="-minimized" goto :run
start /min "" "%~f0" -minimized
exit

:run
SET PROJECT_DIR=E:\vscode ai project\mtg-meta-analyzer
SET PYTHON=python
SET LOG_FILE=%PROJECT_DIR%\logs\background_fill.log
SET TIMESTAMP=%DATE% %TIME%

cd /d "%PROJECT_DIR%"

REM Rotate log if over 5 MB (keeps file manageable)
for %%F in ("%LOG_FILE%") do (
    if %%~zF GTR 5242880 (
        move /y "%LOG_FILE%" "%LOG_FILE%.old" >nul 2>&1
    )
)

echo. >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
echo  MTG Meta Analyzer - Background Fill >> "%LOG_FILE%"
echo  Started: %TIMESTAMP% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

REM ── MTGTop8: recent events (last 2 pages per format) ──────────────────────
echo. >> "%LOG_FILE%"
echo [1/7] MTGTop8 - Standard >> "%LOG_FILE%"
%PYTHON% main.py --format standard --pages 2 --max-events 50 >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo [2/7] MTGTop8 - Pioneer >> "%LOG_FILE%"
%PYTHON% main.py --format pioneer --pages 2 --max-events 50 >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo [3/7] MTGTop8 - Modern >> "%LOG_FILE%"
%PYTHON% main.py --format modern --pages 2 --max-events 50 >> "%LOG_FILE%" 2>&1

REM ── MTGDecks: recent tournament pages ─────────────────────────────────────
echo. >> "%LOG_FILE%"
echo [4/7] MTGDecks - Standard, Pioneer, Modern >> "%LOG_FILE%"
%PYTHON% -m scrapers.mtgdecks --format standard --pages 3 >> "%LOG_FILE%" 2>&1
%PYTHON% -m scrapers.mtgdecks --format pioneer  --pages 3 >> "%LOG_FILE%" 2>&1
%PYTHON% -m scrapers.mtgdecks --format modern   --pages 3 >> "%LOG_FILE%" 2>&1

REM ── MTGMelee: real match W/L data ─────────────────────────────────────────
echo. >> "%LOG_FILE%"
echo [5/7] MTGMelee - Standard, Pioneer, Modern >> "%LOG_FILE%"
%PYTHON% -m scrapers.mtgmelee_scraper --format standard --pages 3 >> "%LOG_FILE%" 2>&1
%PYTHON% -m scrapers.mtgmelee_scraper --format pioneer  --pages 3 >> "%LOG_FILE%" 2>&1
%PYTHON% -m scrapers.mtgmelee_scraper --format modern   --pages 3 >> "%LOG_FILE%" 2>&1

REM ── Scryfall enrichment ───────────────────────────────────────────────────
echo. >> "%LOG_FILE%"
echo [6/7] Scryfall enrichment (new cards only) >> "%LOG_FILE%"
%PYTHON% -m scrapers.scryfall >> "%LOG_FILE%" 2>&1

REM ── Archetype normalization ───────────────────────────────────────────────
echo. >> "%LOG_FILE%"
echo [7/7] Archetype normalization >> "%LOG_FILE%"
%PYTHON% -m analysis.archetypes --apply >> "%LOG_FILE%" 2>&1

REM ── Archive maintenance ───────────────────────────────────────────────────
echo. >> "%LOG_FILE%"
echo [+] Archive maintenance >> "%LOG_FILE%"
%PYTHON% -m db.maintenance >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo  Done: %DATE% %TIME% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
