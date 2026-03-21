@echo off
REM ============================================================
REM  MTG Meta Analyzer - Register 6 AM background fill task
REM  Double-click to run — self-elevates to Administrator.
REM  Adds a SECOND daily task (6 AM) alongside the existing
REM  5 PM task. Both run background_fill.bat silently.
REM ============================================================

REM Self-elevate if not already Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator access...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b
)

SET TASK_NAME=MTG-Meta-Analyzer-Background-6AM
SET PROJECT_DIR=E:\vscode ai project\mtg-meta-analyzer
SET BAT_FILE=%PROJECT_DIR%\background_fill.bat

REM Remove existing task if present
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM Register the 6 AM daily task — window hidden via cmd /b flag
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "cmd /c \"%BAT_FILE%\"" ^
  /sc daily ^
  /st 06:00 ^
  /rl HIGHEST ^
  /f

IF %ERRORLEVEL% EQU 0 (
    echo.
    echo  Task "%TASK_NAME%" registered successfully.
    echo  Runs daily at 6:00 AM local time.
    echo  Logs: %PROJECT_DIR%\logs\background_fill.log
    echo.
    echo  Existing tasks:
    schtasks /query /tn "MTG-Meta-Analyzer-Daily"      2>nul | findstr "TaskName\|Next Run"
    schtasks /query /tn "MTG-Meta-Analyzer-Background-6AM" 2>nul | findstr "TaskName\|Next Run"
    echo.
) ELSE (
    echo.
    echo  ERROR: Task registration failed. Try running as Administrator.
    echo.
)
pause
