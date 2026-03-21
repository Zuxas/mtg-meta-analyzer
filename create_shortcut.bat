@echo off
set APP_DIR=%~dp0

powershell -NoProfile -Command "$desktop = [Environment]::GetFolderPath('Desktop'); $ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut(\"$desktop\MTG Meta Analyzer.lnk\"); $sc.TargetPath = '%APP_DIR%launch_app.bat'; $sc.WorkingDirectory = '%APP_DIR%'; $sc.Description = 'MTG Meta Analyzer'; $sc.Save(); Write-Output \"Shortcut created at: $desktop\MTG Meta Analyzer.lnk\""

echo.
pause
