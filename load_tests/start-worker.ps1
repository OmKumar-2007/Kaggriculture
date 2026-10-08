param([int]$Workers = 2, [int]$FakeSeconds = 0, [switch]$RealEvaluation)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Workers -lt 1 -or $Workers -gt 8) { throw 'Workers must be 1–8.' }
$env:DATABASE_URL = 'postgresql+psycopg://arena:load-only-password@127.0.0.1:15432/neural_coliseum'
$env:REDIS_URL = 'redis://127.0.0.1:16379/0'
$env:STORAGE_BACKEND = 'local'
$env:LOCAL_STORAGE_ROOT = Join-Path $PSScriptRoot 'data/objects'
$env:APP_ENV = 'test'
$env:LOAD_TEST_FAKE_SIMULATION = if ($RealEvaluation) { '0' } else { '1' }
if ($FakeSeconds -gt 0) {
    $env:FAKE_SIMULATION_MIN_SECONDS = [string]$FakeSeconds
    $env:FAKE_SIMULATION_MAX_SECONDS = [string]$FakeSeconds
}
$env:MAX_EVALUATION_WORKERS = [string]$Workers
$env:WORKER_NODE_NAME = 'load-test-laptop'
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'data/objects') | Out-Null
$python = (Get-Command python -ErrorAction Stop).Source
$process = Start-Process -FilePath $python -ArgumentList '-m','backend.worker' -WorkingDirectory (Get-Location).Path -RedirectStandardOutput (Join-Path $PSScriptRoot 'data/worker.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data/worker-errors.log') -WindowStyle Hidden -PassThru
$process.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'data/worker.pid')
$kind = if ($RealEvaluation) { 'real-evaluation' } else { 'fake-evaluation' }
Write-Host "Isolated $kind worker running: PID $($process.Id)"
