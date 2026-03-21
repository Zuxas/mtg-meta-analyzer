@echo off
title MTG Meta Analyzer — Database Builder
color 0A
cd /d "%~dp0"

echo.
echo ============================================================
echo   MTG Meta Analyzer - Database Builder
echo ============================================================
echo.
echo   This window will stay open while the database is built.
echo   Press Ctrl+C at any time to stop safely.
echo   Progress is saved — you can resume by running again.
echo.
echo ============================================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found.
    echo   Install Python 3.10+ from https://python.org and add it to PATH.
    echo.
    pause
    exit /b 1
)

:: Check dependencies are installed
python -c "import requests, bs4, cloudscraper, thefuzz, PyQt6" >nul 2>&1
if errorlevel 1 (
    echo   Installing required packages...
    pip install -r requirements.txt
    echo.
)

:: Run the database builder
python fill_database.py

echo.
echo ============================================================
echo   Done. Press any key to close this window.
echo ============================================================
pause >nul
