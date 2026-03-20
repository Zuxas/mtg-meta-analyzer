@echo off
REM ============================================================
REM  MTG Meta Analyzer - Scryfall Weekly Refresh Scheduler
REM  Double-click to run — self-elevates to Administrator.
REM  Registers a Task Scheduler job that runs every Sunday
REM  at midnight to keep the local card database current.
REM ============================================================

REM Self-elevate if not already running as Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator access...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

SET TASK_NAME=MTG-Scryfall-Weekly

REM Remove existing task if present
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM Register the task — weekly on Sunday at 00:00
schtasks /create /tn "%TASK_NAME%" /tr "cmd /c \"E:\vscode ai project\mtg-meta-analyzer\run_scryfall_weekly.bat\"" /sc weekly /d SUN /st 00:00 /rl HIGHEST /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo  Task "%TASK_NAME%" registered successfully.
    echo  Runs every Sunday at midnight.
    echo  Logs: E:\vscode ai project\mtg-meta-analyzer\logs\scryfall_YYYY-MM-DD.log
    echo.
) ELSE (
    echo.
    echo  ERROR: Task registration failed.
    echo.
)
pause
