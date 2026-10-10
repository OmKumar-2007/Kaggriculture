@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if not exist "%~dp0farmcraft-evaluator\scripts\deployment-manager.ps1" (
  echo FarmCraft launcher support is missing. Restore the repository checkout.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0farmcraft-evaluator\scripts\deployment-manager.ps1"
set "FARMCRAFT_EXIT=%ERRORLEVEL%"
if not "%FARMCRAFT_EXIT%"=="0" (
  echo FarmCraft launcher exited with an error. Review the message above.
  pause
)
exit /b %FARMCRAFT_EXIT%
