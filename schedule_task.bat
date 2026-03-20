@echo off
REM ============================================================
REM  MTG Meta Analyzer - Windows Task Scheduler Setup
REM  Run this ONCE as Administrator to register the daily task.
REM  Task runs every day at 5:00 PM PST (UTC-8).
REM ============================================================

SET PROJECT_DIR=E:\vscode ai project\mtg-meta-analyzer
SET PYTHON=python
SET TASK_NAME=MTG-Meta-Analyzer-Daily

REM Remove existing task if present (allows re-running this script to update)
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM Register the new task
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "cmd /c \"%PROJECT_DIR%\run_daily.bat\"" ^
  /sc daily ^
  /st 17:00 ^
  /rl HIGHEST ^
  /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo Task "%TASK_NAME%" registered successfully.
    echo It will run every day at 5:00 PM.
    echo Log files will appear in: %PROJECT_DIR%\logs\
) ELSE (
    echo.
    echo ERROR: Failed to register task. Make sure you are running as Administrator.
)
pause
