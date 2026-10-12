# Local-only preparation. Does not register a worker or contact Azure.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$directory = Join-Path $root 'config/local-profiles'
$profile = Join-Path $directory 'staging-worker.env'
$credential = Join-Path $directory 'staging-worker.credentials.json'
if (Test-Path -LiteralPath $profile) { throw 'A staging worker profile already exists; inspect it before changing.' }
if (Test-Path -LiteralPath $credential) { throw 'A staging worker credential already exists; inspect it before changing.' }
New-Item -ItemType Directory -Path $directory -Force | Out-Null
@'
FARMCRAFT_API_URL=https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io
WORKER_NAME=FarmCraft Staging Laptop 1
WORKER_CONCURRENCY=1
WORKER_HEARTBEAT_SECONDS=15
WORKER_POLL_SECONDS=8
EVALUATION_TIMEOUT_SECONDS=120
EVALUATION_MEMORY_MB=512
EVALUATION_CPU_LIMIT=1
EVALUATION_PIDS_LIMIT=128
EVALUATOR_IMAGE=nitw-farm-ai-evaluator:2026.10.12
'@ | Set-Content -LiteralPath $profile -Encoding utf8
& icacls $profile /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not restrict the local staging worker profile.' }
Write-Host 'Prepared a separate local staging worker profile. No worker was registered or started.'
Write-Host 'After separate staging approval, set FARMCRAFT_WORKER_ENV_FILE and FARMCRAFT_WORKER_CREDENTIAL_FILE to the two paths in config/local-profiles before registration.'
