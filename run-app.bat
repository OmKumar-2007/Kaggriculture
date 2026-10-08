@echo off
setlocal
cd /d "%~dp0"
echo Starting FarmCraft on this laptop...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-server.ps1" %*
if errorlevel 1 (
    echo FarmCraft startup failed. See the message above.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0health-check.ps1"
if errorlevel 1 (
    echo FarmCraft started, but the health check failed. Check Docker Desktop and the logs.
    pause
    exit /b 1
)
set "FARMCRAFT_PORT=8000"
for /f "tokens=1,* delims==" %%A in ('findstr /b "FARMCRAFT_PORT=" "%~dp0.env"') do set "FARMCRAFT_PORT=%%B"
start "" "http://127.0.0.1:%FARMCRAFT_PORT%/"
start "" "http://127.0.0.1:%FARMCRAFT_PORT%/admin"
echo FarmCraft is running. Close this window when ready; services stay running.
pause
