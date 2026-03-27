@echo off
REM ============================================================
REM  MTG Meta Analyzer - Background Database Fill
REM  Reads formats from data/preferences.json — only scrapes
REM  the formats the user has selected in Settings.
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
SET PYTHONIOENCODING=utf-8
SET LOG_FILE=%PROJECT_DIR%\logs\background_fill.log
SET TIMESTAMP=%DATE% %TIME%

cd /d "%PROJECT_DIR%"

REM Rotate log if over 5 MB
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

REM Delegate to Python script that reads preferences.json for format list
%PYTHON% scripts\run_fill_from_prefs.py >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo  Done: %DATE% %TIME% >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"
