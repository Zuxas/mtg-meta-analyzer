@echo off
REM ============================================================
REM  MTG Meta Analyzer - Weekly Scryfall database refresh
REM  Called by Windows Task Scheduler every Sunday at midnight.
REM  Refreshes the local Scryfall Oracle card database and
REM  re-enriches any new cards added since the last run.
REM ============================================================

REM The folder this .bat lives in (works from any clone or worktree)
SET "PROJECT_DIR=%~dp0"
SET "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
SET PYTHON=python
REM Locale-independent date (%DATE% slicing depends on the regional format)
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "LOG_DATE=%%d"
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
