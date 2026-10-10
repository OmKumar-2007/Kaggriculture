param([string]$ApiUrl, [string]$WorkerName)
$ErrorActionPreference = 'Stop'
$package = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repo = (Resolve-Path (Join-Path $package '..')).Path
if ($env:OS -ne 'Windows_NT') { throw 'This script requires Windows 11.' }
Write-Host "Windows architecture: $env:PROCESSOR_ARCHITECTURE"
if ($env:PROCESSOR_ARCHITECTURE -notin @('AMD64','ARM64')) { throw 'A 64-bit Windows machine is required.' }
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3.11 or 3.12, then rerun setup.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows, then rerun setup.' }
$python = 'py -3.11'
& py -3.11 -c 'import sys; print(sys.version)' 2>$null
if ($LASTEXITCODE -ne 0) { $python = 'py -3.12'; & py -3.12 -c 'import sys; print(sys.version)' }
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or 3.12 is required.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Install Docker Desktop with WSL2, then rerun setup.' }
& wsl --status
if ($LASTEXITCODE -ne 0) { throw 'WSL2 is unavailable. Enable it before setup.' }
& docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop before setup.' }
$config = if ($env:FARMCRAFT_WORKER_ENV_FILE) { $env:FARMCRAFT_WORKER_ENV_FILE } else { Join-Path $package '.env' }
if (-not (Test-Path -LiteralPath $config)) {
    if (-not $ApiUrl) { $ApiUrl = Read-Host 'FarmCraft API HTTPS URL' }
    if (-not $WorkerName) { $WorkerName = Read-Host 'Evaluator laptop name' }
    $parsed = [uri]$ApiUrl
    if ($parsed.Scheme -ne 'https' -and -not ($parsed.Scheme -eq 'http' -and $parsed.Host -in @('127.0.0.1','localhost'))) {
        throw 'The evaluator API URL must be HTTPS (localhost HTTP is for development only).'
    }
    $example = Get-Content -LiteralPath (Join-Path $package '.env.example') -Raw
    $example = $example.Replace('https://your-api.onrender.com', $ApiUrl.TrimEnd('/')).Replace('Evaluation-Laptop-1', $WorkerName)
    New-Item -ItemType Directory -Force -Path (Split-Path $config -Parent) | Out-Null
    [System.IO.File]::WriteAllText($config, $example)
}
$venv = Join-Path $package '.venv'
$workerPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $workerPython)) {
    if ($python -eq 'py -3.11') { & py -3.11 -m venv $venv } else { & py -3.12 -m venv $venv }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $workerPython -c 'import psutil, requests'
if ($LASTEXITCODE -ne 0) {
    & $workerPython -m pip install --disable-pip-version-check -r (Join-Path $package 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Worker dependency installation failed.' }
}
$version = (Get-Content (Join-Path $package 'VERSION') -Raw).Trim()
$image = "nitw-farm-ai-evaluator:$version"
& docker image inspect $image *> $null
if ($LASTEXITCODE -ne 0) {
    & docker build -t $image (Join-Path $repo 'NITW_Farm_AI_Challenge_v1')
    if ($LASTEXITCODE -ne 0) { throw 'Evaluator image build failed.' }
}
& $workerPython (Join-Path $package 'scripts\doctor.py')
if ($LASTEXITCODE -ne 0) { throw 'Evaluator doctor failed.' }
$credentials = if ($env:FARMCRAFT_WORKER_CREDENTIAL_FILE) { $env:FARMCRAFT_WORKER_CREDENTIAL_FILE } else { Join-Path $package 'credentials.json' }
if (-not (Test-Path -LiteralPath $credentials)) {
    & $workerPython (Join-Path $package 'app\worker.py') --register
    if ($LASTEXITCODE -ne 0) { throw 'Worker registration failed.' }
} else {
    Write-Host 'Existing worker credentials preserved. Rotate or revoke through Admin if needed.'
}
& icacls $credentials /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict worker credential file permissions.' }
Write-Host 'Setup complete. Run farmcraft-evaluator\scripts\start-worker.ps1.'
