param([switch]$NoClear)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$package = Join-Path $repo 'farmcraft-evaluator'
$profiles = Join-Path $repo 'config\local-profiles'
$azureSite = Join-Path $profiles 'azure-site.json'
$azureWorker = Join-Path $profiles 'azure-laptop.env'
$azureIdentity = Join-Path $profiles 'azure-worker-credentials.json'
$lastMode = Join-Path $profiles 'last-mode.txt'
$activeMode = Join-Path $profiles 'active-worker-mode.txt'
$pidFile = Join-Path $package 'worker.pid'
$legacy = Join-Path $PSScriptRoot 'launcher.ps1'
$version = (Get-Content -LiteralPath (Join-Path $package 'VERSION') -Raw).Trim()

function Reset-ProfileEnvironment {
    foreach ($name in @('FARMCRAFT_WORKER_ENV_FILE','FARMCRAFT_WORKER_CREDENTIAL_FILE','FARMCRAFT_LAUNCHER_CONFIG_FILE',
                       'FARMCRAFT_API_URL','WORKER_NAME','WORKER_CONCURRENCY','WORKER_HEARTBEAT_SECONDS',
                       'WORKER_POLL_SECONDS','EVALUATION_TIMEOUT_SECONDS','EVALUATION_MEMORY_MB',
                       'EVALUATION_CPU_LIMIT','EVALUATION_PIDS_LIMIT','EVALUATOR_IMAGE')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
}

function Select-Profile([string]$mode) {
    Reset-ProfileEnvironment
    if ($mode -eq '2') {
        $env:FARMCRAFT_WORKER_ENV_FILE = $azureWorker
        $env:FARMCRAFT_WORKER_CREDENTIAL_FILE = $azureIdentity
        $env:FARMCRAFT_LAUNCHER_CONFIG_FILE = $azureSite
    }
}

function Ensure-AzureProfile {
    New-Item -ItemType Directory -Force -Path $profiles | Out-Null
    if (-not (Test-Path -LiteralPath $azureSite)) {
        Copy-Item -LiteralPath (Join-Path $repo 'config\profile-templates\azure-site.example.json') -Destination $azureSite
        Write-Host "Created $azureSite. Enter the deployed Azure frontend and API URLs."
    }
    if (-not (Test-Path -LiteralPath $azureWorker)) {
        Copy-Item -LiteralPath (Join-Path $repo 'config\profile-templates\azure-laptop.env.example') -Destination $azureWorker
        Write-Host "Created $azureWorker. Set FARMCRAFT_API_URL to the same Azure API."
    }
}

function Read-Site([string]$mode) {
    if ($mode -eq '3') {
        $path = Join-Path $package 'launcher.local.json'
        if (Test-Path -LiteralPath $path) { return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
        return [pscustomobject]@{ frontendUrl = ''; apiUrl = '' }
    }
    if (-not (Test-Path -LiteralPath $azureSite)) { return [pscustomobject]@{ frontendUrl = ''; apiUrl = '' } }
    return Get-Content -LiteralPath $azureSite -Raw | ConvertFrom-Json
}

function Confirm-Url([string]$url) {
    if (-not $url -or $url -match 'example|your-') { throw 'Configure the deployed HTTPS URL in the selected local profile first.' }
    $uri = [uri]$url
    if ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost','127.0.0.1'))) {
        throw 'Cloud endpoints must use HTTPS.'
    }
    return $url.TrimEnd('/')
}

function Show-Status([string]$mode) {
    $provider = if ($mode -eq '3') { 'RENDER' } else { 'AZURE' }
    $evaluation = if ($mode -eq '1') { 'AZURE CLOUD (SECURITY GATE CLOSED)' } else { 'LOCAL LAPTOP' }
    $site = Read-Site $mode
    Write-Host "`n================ FARMCRAFT STATUS ================"
    Write-Host "Hosting Provider:      $provider"
    Write-Host "Selected Evaluation:   $evaluation"
    Write-Host "Frontend:              UNKNOWN"
    Write-Host "FastAPI:                UNKNOWN"
    Write-Host "PostgreSQL:             UNKNOWN"
    Write-Host "Object Storage:         UNKNOWN"
    Write-Host "Server Evaluator Mode:  UNKNOWN"
    Write-Host "Round 1 / Round 2:     UNKNOWN / UNKNOWN"
    Write-Host "Azure Credit Remaining: UNKNOWN"
    try {
        $api = Confirm-Url ([string]$site.apiUrl)
        $ready = Invoke-RestMethod -Uri "$api/ready" -TimeoutSec 15
        Write-Host "FastAPI:                $(if ($ready.status -eq 'ready') {'HEALTHY'} else {'UNREADY'})"
        Write-Host "PostgreSQL:             $(if ($ready.checks.database) {'HEALTHY'} else {'UNREADY'})"
        Write-Host "Object Storage:         $(if ($ready.checks.storage) {'HEALTHY'} else {'UNREADY'})"
        $v = Invoke-RestMethod -Uri "$api/api/remote-workers/version" -TimeoutSec 15
        Write-Host "Server Evaluator Mode:  $(if ($v.evaluatorMode) {$v.evaluatorMode} else {'UNKNOWN'})"
        Write-Host "Evaluator Version:      $($v.evaluatorVersion) (local: $version)"
        $event = Invoke-RestMethod -Uri "$api/event/status" -TimeoutSec 15
        $round = Invoke-RestMethod -Uri "$api/tournament/status" -TimeoutSec 15
        Write-Host "Round 1 / Round 2:     $($event.mode) / $($round.status)"
        if ($mode -eq '1' -and $v.evaluatorMode -ne 'AZURE_CLOUD') {
            Write-Warning 'Selected cloud mode differs from the server. Cloud evaluation remains disabled.'
        }
        if ($mode -ne '1' -and $v.evaluatorMode -and $v.evaluatorMode -ne 'LOCAL') {
            Write-Warning 'Selected local mode differs from the server. Do not start this worker.'
        }
    } catch { Write-Warning "Cloud status unavailable: $($_.Exception.Message)" }
    try {
        $web = Confirm-Url ([string]$site.frontendUrl)
        $response = Invoke-WebRequest -Uri $web -UseBasicParsing -TimeoutSec 15
        Write-Host "Frontend:              $(if ($response.StatusCode -eq 200) {'ONLINE'} else {'UNREADY'})"
    } catch { Write-Warning "Frontend status unavailable: $($_.Exception.Message)" }
    if ($mode -ne '1') {
        $docker = & docker info --format '{{.ServerVersion}}' 2>$null
        Write-Host "Local Docker:          $(if ($LASTEXITCODE -eq 0) {"READY ($docker)"} else {'UNREADY'})"
        $credential = if ($mode -eq '2') { $azureIdentity } else { Join-Path $package 'credentials.json' }
        Write-Host "Local identity:        $(if (Test-Path -LiteralPath $credential) {'CONFIGURED'} else {'MISSING'})"
    }
    Write-Host '=================================================='
}

function Invoke-ModeAction([string]$mode, [string]$action) {
    Select-Profile $mode
    if ($action -in @('Start','Stop') -and $mode -ne '1' -and (Test-Path -LiteralPath $pidFile)) {
        $runningMode = if (Test-Path -LiteralPath $activeMode) {
            (Get-Content -LiteralPath $activeMode -Raw).Trim()
        } else { '3' } # Existing launcher-managed workers predate per-mode tracking.
        if ($runningMode -ne $mode) {
            throw "A different environment's evaluator is tracked (mode $runningMode). Return to that mode to stop it."
        }
    }
    if ($mode -in @('1','2')) {
        if ($action -eq 'Setup') {
            Ensure-AzureProfile
            & (Join-Path $repo 'azure\preflight.ps1')
            if ($mode -eq '2') {
                Write-Host 'After Azure API deployment and worker registration are configured, rerun setup to install the laptop evaluator.'
                $site = Read-Site $mode
                $null = Confirm-Url ([string]$site.apiUrl)
                & (Join-Path $PSScriptRoot 'setup-windows.ps1')
            }
            return
        }
        if ($action -eq 'Deploy') { & (Join-Path $repo 'azure\deploy.ps1'); return }
        if ($mode -eq '1') {
            if ($action -eq 'Health') { Show-Status $mode; return }
            if ($action -eq 'Admin') {
                $url = Confirm-Url ([string](Read-Site $mode).frontendUrl)
                Start-Process -FilePath "$url/admin"; return
            }
            if ($action -eq 'Logs') { Write-Host 'Use Azure Portal or Azure CLI for Container Apps logs. No cloud evaluator job is enabled.'; return }
            if ($action -eq 'Stop') { Write-Host 'Cloud evaluations are disabled. No local evaluator was started.'; return }
            throw 'Full Azure cloud evaluation is disabled until untrusted-code isolation is validated. Use Azure + local evaluator.'
        }
    }
    if ($action -eq 'Health') { Show-Status $mode; & $legacy -Action Health; return }
    $legacyAction = switch ($action) {
        'Setup' { 'Setup' }
        'Start' { 'Start' }
        'Deploy' { 'Deploy' }
        'Logs' { 'Logs' }
        'Benchmark' { 'Benchmark' }
        'Admin' { 'Admin' }
        'Stop' { 'Stop' }
        default { throw 'Unknown action.' }
    }
    & $legacy -Action $legacyAction
    if ($LASTEXITCODE -ne 0) { throw "$action failed for the selected environment." }
    if ($action -eq 'Start') {
        New-Item -ItemType Directory -Force -Path $profiles | Out-Null
        [IO.File]::WriteAllText($lastMode, $mode)
        [IO.File]::WriteAllText($activeMode, $mode)
    }
    if ($action -eq 'Stop' -and -not (Test-Path -LiteralPath $pidFile)) {
        Remove-Item -LiteralPath $activeMode -ErrorAction SilentlyContinue
    }
}

function Show-ModeMenu {
    if (-not $NoClear) { Clear-Host }
    $suggestion = if (Test-Path -LiteralPath $lastMode) { (Get-Content -LiteralPath $lastMode -Raw).Trim() } else { '' }
    Write-Host '======================================================'
    Write-Host '                       FARMCRAFT'
    Write-Host '             DEPLOYMENT & EVALUATION MANAGER'
    Write-Host '======================================================'
    Write-Host 'Choose how to run FarmCraft:'
    Write-Host ' [1] FULL AZURE CLOUD'
    Write-Host '     Azure website + Azure backend + cloud evaluations'
    Write-Host '     Cloud evaluation is currently security-gated.'
    Write-Host ' [2] AZURE + LOCAL EVALUATOR'
    Write-Host '     Azure website + Azure backend + this laptop'
    Write-Host ' [3] EXISTING RENDER + LOCAL EVALUATOR'
    Write-Host '     Render Free website + this laptop'
    Write-Host ' [4] SYSTEM CONFIGURATION'
    Write-Host ' [0] EXIT'
    if ($suggestion -in @('1','2','3')) { Write-Host "Last successful mode: $suggestion (suggestion only)" }
    Write-Host '======================================================'
}

function Show-Operations([string]$mode) {
    $label = @{ '1'='FULL AZURE CLOUD'; '2'='AZURE + LOCAL EVALUATOR'; '3'='RENDER + LOCAL EVALUATOR' }[$mode]
    if (-not $NoClear) { Clear-Host }
    Write-Host '======================================================'
    Write-Host '                 FARMCRAFT OPERATIONS'
    Write-Host " Selected Mode: $label"
    Write-Host '======================================================'
    Write-Host ' [1] First-Time Setup'
    Write-Host ' [2] Start FarmCraft'
    Write-Host ' [3] Deploy / Update Application'
    Write-Host ' [4] System Health'
    Write-Host ' [5] Evaluation Workers'
    Write-Host ' [6] View Logs'
    Write-Host ' [7] Run Benchmark'
    Write-Host ' [8] Open Admin Dashboard'
    Write-Host ' [9] Stop Evaluations'
    Write-Host ' [B] Back to Mode Selection'
    Write-Host '======================================================'
}

while ($true) {
    Show-ModeMenu
    $mode = (Read-Host 'Enter your choice').Trim()
    if ($mode -eq '0') { exit 0 }
    if ($mode -eq '4') {
        Write-Host "Profile directory: $profiles"
        Write-Host "Evaluator version: $version"
        Write-Host 'Azure CLI and account: check through First-Time Setup.'
        $null = Read-Host 'Press Enter to continue'
        continue
    }
    if ($mode -notin @('1','2','3')) { Write-Host 'Choose 0-4.'; continue }
    while ($true) {
        Show-Operations $mode
        $choice = (Read-Host 'Enter your choice').Trim().ToUpperInvariant()
        if ($choice -eq 'B') { break }
        $action = @{ '1'='Setup'; '2'='Start'; '3'='Deploy'; '4'='Health'; '5'='Health'; '6'='Logs'; '7'='Benchmark'; '8'='Admin'; '9'='Stop' }[$choice]
        if (-not $action) { Write-Host 'Choose 1-9 or B.'; continue }
        try { Invoke-ModeAction $mode $action }
        catch { Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red }
        $null = Read-Host 'Press Enter to continue'
    }
}
