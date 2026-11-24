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

REM NOTE (#16): this .bat no longer self-relaunches minimized. The old
REM `start /min "" "%~f0" -minimized` + `exit` returned exit 0 to Task Scheduler
REM INSTANTLY, before any work ran, so a failed nightly fill always looked
REM successful. Task Scheduler already runs the task hidden; for a double-click,
REM launch it from a minimized shortcut if you want the window out of the way.
REM The folder this .bat lives in (works from any clone or worktree)
SET "PROJECT_DIR=%~dp0"
SET "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
SET PYTHON=python
SET PYTHONIOENCODING=utf-8
SET LOG_FILE=%PROJECT_DIR%\logs\background_fill.log
SET TIMESTAMP=%DATE% %TIME%

cd /d "%PROJECT_DIR%"
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs"

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
SET FILL_RC=%ERRORLEVEL%

REM Archetype sync (quick — identifies unclassified archetypes)
echo. >> "%LOG_FILE%"
echo [+] Archetype sync >> "%LOG_FILE%"
%PYTHON% scripts\sync_archetypes.py >> "%LOG_FILE%" 2>&1

echo. >> "%LOG_FILE%"
echo  Done: %DATE% %TIME%  (fill exit code: %FILL_RC%) >> "%LOG_FILE%"
echo ============================================================ >> "%LOG_FILE%"

REM Propagate the pipeline's exit code so Task Scheduler sees failures (#16).
exit /b %FILL_RC%
