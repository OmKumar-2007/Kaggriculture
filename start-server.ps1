param([int]$Workers = 2)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($Workers -lt 1 -or $Workers -gt 8) { throw 'Workers must be between 1 and 8.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop is required.' }
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $desktopCandidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/Docker Desktop.exe'),
        (Join-Path $env:ProgramFiles 'Docker/Docker/Docker Desktop.exe')
    )
    $desktop = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $desktop) { throw 'Docker Desktop is installed but not running. Start it and run this file again.' }
    Write-Host 'Starting Docker Desktop...'
    Start-Process -FilePath $desktop -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    }
    if (-not $ready) { throw 'Docker Desktop did not become ready within two minutes.' }
}
$python = (Get-Command python -ErrorAction Stop).Source
& $python -c 'import rq, redis, sqlalchemy, psycopg, psutil'
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing host worker dependencies...'
    & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-worker.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Host worker dependency installation failed.' }
}
$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    $secure = Read-Host 'Choose organizer password (12+ characters)' -AsSecureString
    $plain = [System.Net.NetworkCredential]::new('', $secure).Password
    if ($plain.Length -lt 12) { throw 'Organizer password must be at least 12 characters.' }
    $salt = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(18)).ToLowerInvariant()
    $key = [Security.Cryptography.Rfc2898DeriveBytes]::new([Text.Encoding]::UTF8.GetBytes($plain), [Text.Encoding]::UTF8.GetBytes($salt), 310000, [Security.Cryptography.HashAlgorithmName]::SHA256)
    $hash = [Convert]::ToHexString($key.GetBytes(32)).ToLowerInvariant()
    $plain = $null
    $existingVolume = docker volume ls --format '{{.Name}}' | Where-Object { $_ -eq 'kaggriculture_postgres_data' }
    $postgresPassword = if ($existingVolume) { 'local-arena' } else { [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24)).ToLowerInvariant() }
    $sessionSecret = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(48)).ToLowerInvariant()
    $hashLine = "ADMIN_PASSWORD_HASH='pbkdf2_sha256`$310000`$$($salt)`$$($hash)'"
    @("POSTGRES_PASSWORD=$postgresPassword", $hashLine, "ADMIN_SESSION_SECRET=$sessionSecret", 'FARMCRAFT_BIND_IP=0.0.0.0', 'FARMCRAFT_PORT=8000', "MAX_EVALUATION_WORKERS=$Workers", 'EVALUATION_TIMEOUT_SECONDS=120', 'EVALUATION_MEMORY_MB=512', 'EVALUATION_CPU_LIMIT=1', 'MAX_SUBMISSION_SIZE_KB=256') | Set-Content -LiteralPath $envFile -Encoding ascii
    Write-Host 'Created .env. Keep it private and backed up.'
}
Get-Content -LiteralPath $envFile | ForEach-Object {
    if ($_ -match '^([A-Z_][A-Z0-9_]*)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim("'"), 'Process') }
}
$env:DATABASE_URL = "postgresql+psycopg://arena:$($env:POSTGRES_PASSWORD)@127.0.0.1:5432/neural_coliseum"
$env:REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:STORAGE_BACKEND = 'local'
$env:LOCAL_STORAGE_ROOT = Join-Path $PSScriptRoot 'data/objects'
$env:APP_ENV = 'local'
$env:NEURAL_COLISEUM_TRUSTED_LOCAL = '0'
$env:MAX_EVALUATION_WORKERS = [string]$Workers
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'data/objects') | Out-Null
docker build -t nitw-farm-ai-evaluator (Join-Path $PSScriptRoot 'NITW_Farm_AI_Challenge_v1')
if ($LASTEXITCODE -ne 0) { throw 'Evaluator image build failed.' }
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose startup failed.' }
$pidFile = Join-Path $PSScriptRoot 'data/host-worker.pid'
if (Test-Path -LiteralPath $pidFile) {
    $oldId = [int](Get-Content -LiteralPath $pidFile -Raw)
    if (Get-Process -Id $oldId -ErrorAction SilentlyContinue) { Write-Host "Host worker already running (PID $oldId)."; exit 0 }
}
$worker = Start-Process -FilePath $python -ArgumentList '-m','backend.worker' -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $PSScriptRoot 'data/host-worker.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data/host-worker-errors.log') -WindowStyle Hidden -PassThru
$worker.Id | Set-Content -LiteralPath $pidFile
$port = if ($env:FARMCRAFT_PORT) { $env:FARMCRAFT_PORT } else { '8000' }
Write-Host "FarmCraft: http://127.0.0.1:$port/"
Write-Host "Organizer: http://127.0.0.1:$port/admin"
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.InterfaceAlias -notmatch 'vEthernet|Docker|WSL' } | ForEach-Object { Write-Host "LAN candidate: http://$($_.IPAddress):$port/" }
Write-Host 'Run .\health-check.ps1 for service status.'
