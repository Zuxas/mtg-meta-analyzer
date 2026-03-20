@echo off
REM ============================================================
REM  MTG Meta Analyzer - Daily scraper run
REM  Called by Windows Task Scheduler every day at 5:00 PM PST.
REM  Logs output to logs\YYYY-MM-DD.log
REM ============================================================

SET PROJECT_DIR=E:\vscode ai project\mtg-meta-analyzer
SET PYTHON=python
SET LOG_DATE=%DATE:~10,4%-%DATE:~4,2%-%DATE:~7,2%
SET LOG_FILE=%PROJECT_DIR%\logs\%LOG_DATE%.log

cd /d "%PROJECT_DIR%"

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
