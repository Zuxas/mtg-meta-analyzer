@echo off
REM ============================================================
REM  MTG Meta Analyzer - Weekly Scryfall database refresh
REM  Called by Windows Task Scheduler every Sunday at midnight.
REM  Refreshes the local Scryfall Oracle card database and
REM  re-enriches any new cards added since the last run.
REM ============================================================

SET PROJECT_DIR=E:\vscode ai project\mtg-meta-analyzer
SET PYTHON=python
SET LOG_DATE=%DATE:~10,4%-%DATE:~4,2%-%DATE:~7,2%
SET LOG_FILE=%PROJECT_DIR%\logs\scryfall_%LOG_DATE%.log

cd /d "%PROJECT_DIR%"
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs"

echo ============================================================ >> "%LOG_FILE%"
echo MTG Meta Analyzer - Weekly Scryfall Refresh >> "%LOG_FILE%"
echo Date: %DATE%  Time: %TIME% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

echo. >> "%LOG_FILE%"
echo [1/2] Downloading fresh Scryfall oracle database... >> "%LOG_FILE%"
%PYTHON% -m scrapers.scryfall --download >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo [2/2] Enriching new cards from fresh database... >> "%LOG_FILE%"
%PYTHON% -m scrapers.scryfall >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo Done. >> "%LOG_FILE%"
