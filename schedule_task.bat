@echo off
REM ============================================================
REM  MTG Meta Analyzer - Windows Task Scheduler Setup
REM  Double-click to run — it will self-elevate to Administrator.
REM  Task runs every day at 5:00 PM PST (UTC-8).
REM ============================================================

REM Self-elevate if not already running as Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator access...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

SET TASK_NAME=MTG-Meta-Analyzer-Daily

REM Remove existing task if present
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM Register the task — quotes handle the space in the project folder path
schtasks /create /tn "%TASK_NAME%" /tr "cmd /c \"E:\vscode ai project\mtg-meta-analyzer\run_daily.bat\"" /sc daily /st 17:00 /rl HIGHEST /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo  Task "%TASK_NAME%" registered successfully.
    echo  Runs daily at 5:00 PM local time.
    echo  Logs: E:\vscode ai project\mtg-meta-analyzer\logs\
    echo.
) ELSE (
    echo.
    echo  ERROR: Task registration failed.
    echo.
)
pause
