@echo off
setlocal
cd /d "%~dp0"

set "APP_ENV=development"
set "STORAGE_BACKEND=local"

where docker >nul 2>nul
if errorlevel 1 goto docker_missing

docker compose version >nul 2>nul
if errorlevel 1 goto compose_missing

set "ADMIN_PASSWORD="
set /p "ADMIN_PASSWORD=Organizer password for this run: "
if not defined ADMIN_PASSWORD goto password_missing
for /f "delims=" %%H in ('powershell.exe -NoProfile -Command "$salt=[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(18)).TrimEnd('=').Replace('+','-').Replace('/','_'); $bytes=[Text.Encoding]::UTF8.GetBytes($env:ADMIN_PASSWORD); $k=[Security.Cryptography.Rfc2898DeriveBytes]::new($bytes,[Text.Encoding]::UTF8.GetBytes($salt),310000,[Security.Cryptography.HashAlgorithmName]::SHA256); Write-Output ('pbkdf2_sha256$310000$'+$salt+'$'+[Convert]::ToHexString($k.GetBytes(32)).ToLowerInvariant())"') do set "ADMIN_PASSWORD_HASH=%%H"
for /f "delims=" %%S in ('powershell.exe -NoProfile -Command "[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48)).TrimEnd('=').Replace('+','-').Replace('/','_')"') do set "ADMIN_SESSION_SECRET=%%S"
set "ADMIN_PASSWORD="
if not defined ADMIN_PASSWORD_HASH goto credential_setup_failed

echo Starting PostgreSQL, Redis, API, and simulation worker...
docker compose up -d --build postgres redis api worker
if errorlevel 1 goto startup_failed

echo Starting the frontend at http://127.0.0.1:5173/
start "FarmCraft Frontend" cmd /k "cd /d ""%~dp0frontend"" ^&^& npm.cmd run dev -- --host 127.0.0.1 --port 5173"
echo.
echo App: http://127.0.0.1:5173/
echo Organizer control room: http://127.0.0.1:5173/admin
echo API: http://127.0.0.1:8000/
echo Docker services keep running after this window closes. Stop them with: docker compose down
pause
exit /b 0

:docker_missing
echo Docker is not installed or not on PATH. Install Docker Desktop, then run this file again.
pause
exit /b 1

:compose_missing
echo Docker Compose is unavailable. Update Docker Desktop, then run this file again.
pause
exit /b 1

:password_missing
echo An organizer password is required.
pause
exit /b 1

:credential_setup_failed
echo Could not create the organizer password hash. Confirm PowerShell is available.
pause
exit /b 1

:startup_failed
echo The Docker stack failed to start. Check Docker Desktop is running, then inspect with: docker compose logs
pause
exit /b 1
