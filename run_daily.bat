@echo off
REM ============================================================
REM  MTG Meta Analyzer - Daily scraper run
REM  Called by Windows Task Scheduler every day at 5:00 PM PST.
REM  Logs output to logs\YYYY-MM-DD.log
REM ============================================================

REM The folder this .bat lives in (works from any clone or worktree)
SET "PROJECT_DIR=%~dp0"
SET "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
SET PYTHON=python
SET PYTHONIOENCODING=utf-8
REM Locale-independent date (%DATE% slicing depends on the regional format)
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "LOG_DATE=%%d"
SET LOG_FILE=%PROJECT_DIR%\logs\%LOG_DATE%.log

cd /d "%PROJECT_DIR%"
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs"

echo ============================================================ >> "%LOG_FILE%"
echo MTG Meta Analyzer - Daily Run >> "%LOG_FILE%"
echo Date: %DATE%  Time: %TIME% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

echo. >> "%LOG_FILE%"
echo [1/2] Scraping today's Standard events... >> "%LOG_FILE%"
%PYTHON% main.py --format standard --pages 1 --max-events 50 >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo [2/2] Running archive maintenance... >> "%LOG_FILE%"
%PYTHON% -m db.maintenance --format standard >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo Done. >> "%LOG_FILE%"
