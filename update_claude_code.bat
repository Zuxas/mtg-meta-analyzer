@echo off
:: Self-elevate to Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -WindowStyle Hidden -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs -Wait"
    exit /b
)

echo.
echo  Updating Claude Code to latest version...
echo.
npm i -g @anthropic-ai/claude-code
if %errorlevel% equ 0 (
    echo.
    echo  Claude Code updated successfully.
) else (
    echo.
    echo  Update failed. Make sure Node.js and npm are installed.
)
echo.
pause
