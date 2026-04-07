@echo off
setlocal EnableDelayedExpansion
SET PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title MTG Meta Analyzer

:menu
cls
echo.
echo  ========================================
echo   MTG Meta Analyzer
echo  ========================================
echo.
echo   1. Launch App
echo   2. Build Database (first-time setup)
echo   3. Run Background Fill Now
echo   4. Register Scheduled Tasks (Admin)
echo   5. Create Desktop Shortcut
echo   6. Refresh Scryfall Data
echo   7. Update Claude Code
echo.
echo   0. Exit
echo.
set /p choice="  Select: "

if "%choice%"=="1" goto launch
if "%choice%"=="2" goto fill_db
if "%choice%"=="3" goto bg_fill
if "%choice%"=="4" goto register_tasks
if "%choice%"=="5" goto shortcut
if "%choice%"=="6" goto scryfall
if "%choice%"=="7" goto update_claude
if "%choice%"=="0" exit /b
goto menu

:: ──────────────────────────────────────────
:launch
:: ──────────────────────────────────────────
echo Starting MTG Meta Analyzer...
start "" pythonw run_gui.py
exit /b

:: ──────────────────────────────────────────
:fill_db
:: ──────────────────────────────────────────
cls
echo.
echo  Building database (this may take a while)...
echo.
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install Python 3.13+ first.
    pause
    goto menu
)
python -c "import requests, bs4, cloudscraper, thefuzz, PyQt6" >nul 2>&1
if errorlevel 1 (
    echo  Installing dependencies...
    pip install -r requirements.txt
)
python fill_database.py
echo.
pause
goto menu

:: ──────────────────────────────────────────
:bg_fill
:: ──────────────────────────────────────────
cls
echo.
echo  Running background fill (reads your format preferences)...
echo.
if not exist logs mkdir logs
python scripts/run_fill_from_prefs.py 2>&1 | tee logs/manual_fill_%date:~-4%%date:~4,2%%date:~7,2%.log
echo.
echo  Done. Check logs/ for details.
pause
goto menu

:: ──────────────────────────────────────────
:register_tasks
:: ──────────────────────────────────────────
cls
echo.
echo  Registering all 3 scheduled tasks (requires Admin)...
echo.

:: Check for admin
net session >nul 2>&1
if errorlevel 1 (
    echo  Elevating to Administrator...
    powershell -Command "Start-Process -FilePath '%~f0' -ArgumentList 'admin_tasks' -Verb RunAs"
    goto menu
)

:admin_tasks
:: 6 AM Background Fill
schtasks /delete /tn "MTG-Meta-Analyzer-Background-6AM" /f >nul 2>&1
schtasks /create /tn "MTG-Meta-Analyzer-Background-6AM" /tr "\"%~dp0background_fill.bat\"" /sc daily /st 06:00 /rl HIGHEST /f
echo  [OK] 6:00 AM daily background fill registered.

:: 5 PM Daily Standard
schtasks /delete /tn "MTG-Meta-Analyzer-Daily" /f >nul 2>&1
schtasks /create /tn "MTG-Meta-Analyzer-Daily" /tr "\"%~dp0run_daily.bat\"" /sc daily /st 17:00 /rl HIGHEST /f
echo  [OK] 5:00 PM daily Standard scrape registered.

:: Sunday Scryfall
schtasks /delete /tn "MTG-Scryfall-Weekly" /f >nul 2>&1
schtasks /create /tn "MTG-Scryfall-Weekly" /tr "\"%~dp0run_scryfall_weekly.bat\"" /sc weekly /d SUN /st 00:00 /rl HIGHEST /f
echo  [OK] Sunday midnight Scryfall refresh registered.

echo.
echo  All 3 tasks registered. Verify with:
schtasks /query /fo list /tn "MTG-Meta-Analyzer-Background-6AM" 2>nul | findstr "TaskName Status"
schtasks /query /fo list /tn "MTG-Meta-Analyzer-Daily" 2>nul | findstr "TaskName Status"
schtasks /query /fo list /tn "MTG-Scryfall-Weekly" 2>nul | findstr "TaskName Status"
echo.
pause
goto menu

:: ──────────────────────────────────────────
:shortcut
:: ──────────────────────────────────────────
cls
echo  Creating desktop shortcut...
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut([System.IO.Path]::Combine($ws.SpecialFolders('Desktop'), 'MTG Meta Analyzer.lnk')); $sc.TargetPath = '%~dp0launch_app.bat'; $sc.WorkingDirectory = '%~dp0'; $sc.Save()"
echo  [OK] Shortcut created on Desktop.
echo.
pause
goto menu

:: ──────────────────────────────────────────
:scryfall
:: ──────────────────────────────────────────
cls
echo.
echo  Refreshing Scryfall card database...
echo.
python -m scrapers.scryfall --download
python -m scrapers.scryfall
echo.
echo  Done.
pause
goto menu

:: ──────────────────────────────────────────
:update_claude
:: ──────────────────────────────────────────
cls
echo.
echo  Updating Claude Code...
net session >nul 2>&1
if errorlevel 1 (
    powershell -Command "Start-Process -FilePath 'npm' -ArgumentList 'i -g @anthropic-ai/claude-code' -Verb RunAs -Wait"
) else (
    npm i -g @anthropic-ai/claude-code
)
echo.
echo  Done.
pause
goto menu
