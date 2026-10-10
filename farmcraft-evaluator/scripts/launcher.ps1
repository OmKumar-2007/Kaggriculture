param([ValidateSet('Menu','Setup','Start','Deploy','EventDay','Health','Stop','Logs','Benchmark','Admin')][string]$Action='Menu')
$ErrorActionPreference = 'Stop'
$package = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repo = (Resolve-Path (Join-Path $package '..')).Path
$logDir = Join-Path $package 'logs'
$pidFile = Join-Path $package 'worker.pid'
$localFile = if ($env:FARMCRAFT_LAUNCHER_CONFIG_FILE) { $env:FARMCRAFT_LAUNCHER_CONFIG_FILE } else { Join-Path $package 'launcher.local.json' }
$envFile = if ($env:FARMCRAFT_WORKER_ENV_FILE) { $env:FARMCRAFT_WORKER_ENV_FILE } else { Join-Path $package '.env' }
$credentialFile = if ($env:FARMCRAFT_WORKER_CREDENTIAL_FILE) { $env:FARMCRAFT_WORKER_CREDENTIAL_FILE } else { Join-Path $package 'credentials.json' }
$version = (Get-Content -LiteralPath (Join-Path $package 'VERSION') -Raw).Trim()

function Read-LocalConfig {
    if (-not (Test-Path -LiteralPath $localFile)) { return @{} }
    $data = Get-Content -LiteralPath $localFile -Raw | ConvertFrom-Json
    $result = @{}
    foreach ($name in @('frontendUrl','apiUrl','apiDeployHook','webDeployHook')) {
        if ($data.PSObject.Properties.Name -contains $name) { $result[$name] = [string]$data.$name }
    }
    return $result
}

function Read-WorkerConfig {
    $values = @{}
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            if ($line -match '^\s*([A-Z_][A-Z_0-9]*)=(.*)$') { $values[$Matches[1]] = $Matches[2].Trim().Trim('"', "'") }
        }
    }
    return $values
}

function Cloud-Config {
    $local = Read-LocalConfig
    $worker = Read-WorkerConfig
    $blueprint = Get-Content -LiteralPath (Join-Path $repo 'render.yaml') -Raw
    $frontend = if ($local.frontendUrl) { $local.frontendUrl } elseif ($blueprint -match '(?m)^\s*value:\s*(https://[^\s]+onrender\.com)\s*$') { $Matches[1] } else { '' }
    if ($local.apiUrl -and $worker.FARMCRAFT_API_URL -and
        $local.apiUrl.TrimEnd('/') -ne $worker.FARMCRAFT_API_URL.TrimEnd('/')) {
        throw "API URL mismatch between $localFile and $envFile. Resolve it before starting a worker."
    }
    $api = if ($local.apiUrl) { $local.apiUrl } elseif ($worker.FARMCRAFT_API_URL) { $worker.FARMCRAFT_API_URL } else { '' }
    return @{ Frontend=$frontend.TrimEnd('/'); Api=$api.TrimEnd('/'); Worker=$worker; Local=$local }
}

function Require-ApiUrl($config) {
    if (-not $config.Api -or $config.Api -match 'your-api') { throw "Set FARMCRAFT_API_URL in $envFile using this deployment's API HTTPS URL." }
    $uri = [uri]$config.Api
    if ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost','127.0.0.1'))) {
        throw 'The evaluator API must use HTTPS; only localhost development may use HTTP.'
    }
}

function Request-Json([string]$url, [hashtable]$headers=@{}, [int]$attempts=3) {
    for ($i=1; $i -le $attempts; $i++) {
        try { return Invoke-RestMethod -Method Get -Uri $url -Headers $headers -TimeoutSec 25 -ErrorAction Stop }
        catch {
            if ($i -eq $attempts) { throw "Could not reach $([uri]$url).Host at $([uri]$url).AbsolutePath after $attempts attempts: $($_.Exception.Message)" }
            Start-Sleep -Seconds ([Math]::Min(4*$i, 12))
        }
    }
}

function Request-Web([string]$url) {
    for ($i=1; $i -le 3; $i++) {
        try { return Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 25 -ErrorAction Stop }
        catch {
            if ($i -eq 3) { throw "Frontend did not respond after three attempts: $($_.Exception.Message)" }
            Start-Sleep -Seconds (4*$i)
        }
    }
}

function Test-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI missing. Install Docker Desktop with WSL2.' }
    $null = & docker info --format '{{.ServerVersion}}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is stopped. Start Docker Desktop and wait for Engine Running.' }
}

function Test-Image($config) {
    $image = if ($config.Worker.EVALUATOR_IMAGE) { $config.Worker.EVALUATOR_IMAGE } else { "nitw-farm-ai-evaluator:$version" }
    $null = & docker image inspect $image 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Evaluator image $image is missing. Choose First-Time Setup." }
    return $image
}

function Read-Identity {
    if (-not (Test-Path -LiteralPath $credentialFile)) { throw 'Worker credentials missing. Create a one-use token in Admin and choose First-Time Setup.' }
    $identity = Get-Content -LiteralPath $credentialFile -Raw | ConvertFrom-Json
    if (-not $identity.workerId -or -not $identity.credential) { throw 'Worker credentials are incomplete. Re-register through Admin.' }
    return $identity
}

function Get-OwnWorker($config) {
    $identity = Read-Identity
    $headers = @{ Authorization = "Bearer $($identity.workerId).$($identity.credential)" }
    try { return Request-Json "$($config.Api)/api/remote-workers/me" $headers 2 }
    catch { throw "Worker authentication or status check failed. Confirm cloud API is updated and this laptop is not revoked. $($_.Exception.Message)" }
}

function Get-WorkerProcess {
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    $savedId = 0
    if (-not [int]::TryParse((Get-Content -LiteralPath $pidFile -Raw).Trim(), [ref]$savedId)) { Remove-Item -LiteralPath $pidFile; return $null }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$savedId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -and $process.CommandLine.Contains((Join-Path $PSScriptRoot 'start-worker.ps1'))) { return $process }
    Remove-Item -LiteralPath $pidFile
    return $null
}

function Find-OtherWorker {
    $scriptPath = Join-Path $PSScriptRoot 'start-worker.ps1'
    $workerPath = Join-Path $package 'app\worker.py'
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and ($_.CommandLine.Contains($scriptPath) -or $_.CommandLine.Contains($workerPath))
    })
}

function Check-Cloud($config) {
    Require-ApiUrl $config
    if (-not $config.Frontend) { throw "Set frontendUrl in $localFile to this deployment's frontend URL." }
    $web = Request-Web $config.Frontend
    if ($web.StatusCode -ne 200 -or $web.Content -notmatch 'FarmCraft|farmcraft') { throw 'Frontend response is not the FarmCraft site.' }
    $health = Request-Json "$($config.Api)/health"
    if ($health.status -ne 'ok') { throw 'API /health did not identify a healthy FarmCraft backend.' }
    $ready = Request-Json "$($config.Api)/ready"
    if ($ready.status -ne 'ready' -or -not $ready.checks.database -or -not $ready.checks.storage -or -not $ready.checks.redis) { throw 'API /ready reports unavailable database, object storage, or session Redis.' }
    $remote = Request-Json "$($config.Api)/api/remote-workers/version"
    if ($remote.evaluatorMode -and $remote.evaluatorMode -ne 'LOCAL') { throw "Server evaluator mode is $($remote.evaluatorMode); local worker claims are disabled." }
    $sha = (Get-FileHash -LiteralPath (Join-Path $repo 'config/evaluation.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($remote.evaluatorVersion -ne $version -or $remote.evaluationConfigSha256 -ne $sha) { throw 'Evaluator version or evaluation configuration hash differs from the cloud API. Deploy the matching branch before starting.' }
    return $ready
}

function Check-Resources($config) {
    $computer = Get-CimInstance Win32_ComputerSystem
    $availableGiB = [Math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1048576, 1)
    $cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
    $need = [Math]::Max(2, [int]$config.Worker.WORKER_CONCURRENCY)
    if ($availableGiB -lt $need) { throw "Only $availableGiB GiB RAM available; configured concurrency needs at least $need GiB. Close apps or lower the setting after benchmarking." }
    if ($cpu -lt 2) { throw 'At least two logical CPU cores are required for the evaluator.' }
    Write-Host "Resources: $availableGiB GiB free RAM, $cpu logical CPUs, $($computer.Model)"
}

function Show-Setup {
    Write-Host "`nChecking Windows evaluator prerequisites..."
    if ($env:OS -ne 'Windows_NT' -or [Environment]::Is64BitOperatingSystem -ne $true) { throw 'A 64-bit Windows 10/11 laptop is required.' }
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt 19041) { throw 'Windows 10 version 2004 or later is required for WSL2; Windows 11 is preferred.' }
    if ($build -lt 22000) { Write-Warning 'Windows 10 detected. Windows 11 is preferred for the event laptop.' }
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Python launcher missing. Install Python 3.11 or 3.12 from python.org.' }
    & py -3.11 -c 'import sys' 2>$null
    if ($LASTEXITCODE -ne 0) { & py -3.12 -c 'import sys' 2>$null; if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or 3.12.' } }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git missing. Install Git for Windows.' }
    if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) { throw 'WSL2 missing. Enable WSL2 before Docker Desktop setup.' }
    & wsl --status
    if ($LASTEXITCODE -ne 0) { throw 'WSL2 is unavailable. Enable it and restart Windows yourself before setup.' }
    Test-Docker
    Check-Resources (Cloud-Config)
    $diskGiB = [Math]::Round((Get-PSDrive -Name ([IO.Path]::GetPathRoot($repo).TrimEnd(':','\'))).Free / 1GB, 1)
    if ($diskGiB -lt 2) { throw "Only $diskGiB GiB free disk; 2 GiB is required." }
    $config = Cloud-Config
    if (-not $config.Api -or $config.Api -match 'your-api') {
        Write-Host 'The cloud API is not configured. Create the free Blueprint first:'
        Write-Host 'https://dashboard.render.com/blueprint/new?repo=https://github.com/OmKumar-2007/Kaggriculture'
        Write-Host 'Configure Neon, Upstash, and the sync:false secrets in Render.'
        $apiUrl = (Read-Host 'Enter the deployed API HTTPS URL, or press Enter to return').Trim().TrimEnd('/')
        if (-not $apiUrl) { throw 'Cloud API URL is required for worker registration.' }
        $uri = [uri]$apiUrl
        if ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost','127.0.0.1'))) { throw 'API URL must use HTTPS.' }
        $name = (Read-Host 'Evaluator laptop name (default Evaluation-Laptop-1)').Trim()
        if (-not $name) { $name = 'Evaluation-Laptop-1' }
        if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9 _-]{2,119}$') { throw 'Worker name must be 3-120 letters, digits, spaces, underscores, or hyphens.' }
        if (-not (Test-Path -LiteralPath $envFile)) {
            $template = Get-Content -LiteralPath (Join-Path $package '.env.example') -Raw
            [IO.File]::WriteAllText($envFile, $template.Replace('https://your-api.onrender.com', $apiUrl).Replace('Evaluation-Laptop-1', $name))
        } else { throw "Existing $envFile needs FARMCRAFT_API_URL set; it was not overwritten." }
        $config = Cloud-Config
    }
    Require-ApiUrl $config
    $null = Check-Cloud $config
    & (Join-Path $PSScriptRoot 'setup-windows.ps1')
    $config = Cloud-Config
    Test-Docker
    $null = Test-Image $config
    $null = Check-Cloud $config
    $own = Get-OwnWorker $config
    Write-Host "`nFARMCRAFT EVALUATOR SETUP COMPLETE"
    Write-Host "Docker: READY | Cloud API: CONNECTED | Worker: $($own.name) ($($own.status))"
    Write-Host 'Use Option 2 to start the evaluation server.'
}

function Start-Evaluator {
    $config = Cloud-Config
    if ($running = Get-WorkerProcess) { Write-Host "Evaluator already running (PID $($running.ProcessId))."; return }
    if (@(Find-OtherWorker).Count) { throw 'Another FarmCraft evaluator process is running outside this launcher. Stop it before starting another copy.' }
    Test-Docker
    Require-ApiUrl $config
    if (-not (Test-Path -LiteralPath (Join-Path $package '.venv/Scripts/python.exe'))) { throw 'Python environment missing. Choose First-Time Setup.' }
    Check-Resources $config
    $null = Check-Cloud $config
    $image = Test-Image $config
    $own = Get-OwnWorker $config
    if ($own.status -eq 'revoked') { throw 'Worker registration was revoked.' }
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | Remove-Item -ErrorAction SilentlyContinue
    $stdout = Join-Path $logDir ("worker-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
    $stderr = [IO.Path]::ChangeExtension($stdout, '.err.log')
    $started = Get-Date
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + (Join-Path $PSScriptRoot 'start-worker.ps1') + '"')) -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $process.Id | Set-Content -LiteralPath $pidFile
    for ($i=0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 3
        if (-not (Get-WorkerProcess)) { throw "Evaluator exited during startup. Read $stderr and $stdout" }
        try {
            $state = Get-OwnWorker $config
            if ($state.lastHeartbeat -and [datetime]::Parse($state.lastHeartbeat).ToUniversalTime() -gt $started.ToUniversalTime() -and $state.status -in @('busy','idle','active')) {
                Write-Host "`nEVALUATION SERVER READY"
                Write-Host "Worker: $($state.name) | API: $($config.Api) | Docker image: $image"
                Write-Host "Concurrency: $($config.Worker.WORKER_CONCURRENCY) | Heartbeat: confirmed | PID: $($process.Id)"
                return
            }
        } catch { Write-Warning $_.Exception.Message }
    }
    throw "Worker process started, but no fresh cloud heartbeat was confirmed. Inspect $stderr and Admin -> Workers & Devices."
}

function Stop-Evaluator {
    $running = Get-WorkerProcess
    if (-not $running) { Write-Host 'No launcher-managed evaluator is running.'; return }
    & (Join-Path $PSScriptRoot 'stop-worker.ps1')
    for ($i=0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 3
        if (-not (Get-WorkerProcess)) { Write-Host 'Evaluator stopped gracefully. Cloud jobs and results were preserved.'; return }
    }
    Write-Warning 'Evaluator still running after three minutes. It may be finishing or cancelling a match.'
    if ((Read-Host 'Type FORCE to stop only this tracked evaluator process') -eq 'FORCE') {
        $running = Get-WorkerProcess
        if ($running) { Stop-Process -Id $running.ProcessId -Force; Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue; Write-Warning 'Tracked controller force-stopped. Check Admin for lease recovery.' }
    }
}

function Show-Health {
    $config = Cloud-Config
    $cloudReady = $false
    $localReady = $false
    $heartbeatReady = $false
    Write-Host "`n================ FARMCRAFT HEALTH ================"
    Write-Host "Frontend: $($config.Frontend)"
    Write-Host "API: $($config.Api)"
    try { $ready = Check-Cloud $config; $cloudReady = $true; Write-Host "Cloud: READY | PostgreSQL: HEALTHY | Object storage: HEALTHY | Session Redis: HEALTHY" }
    catch { Write-Host "Cloud: UNVERIFIED - $($_.Exception.Message)" }
    try { Test-Docker; Write-Host 'Docker: HEALTHY'; $null = Test-Image $config; $localReady = $true; Write-Host 'Evaluator image: READY' }
    catch { Write-Host "Local Docker/image: UNREADY - $($_.Exception.Message)" }
    Write-Host "Python environment: $(if (Test-Path -LiteralPath (Join-Path $package '.venv/Scripts/python.exe')) {'READY'} else {'MISSING'})"
    $running = Get-WorkerProcess
    Write-Host "Worker process: $(if ($running) {"RUNNING ($($running.ProcessId))"} else {'STOPPED'})"
    try { Require-ApiUrl $config; $state = Get-OwnWorker $config; $heartbeatReady = [bool]($running -and $state.status -in @('busy','idle') -and $state.lastHeartbeat -and ([datetime]::Parse($state.lastHeartbeat).ToUniversalTime() -gt (Get-Date).ToUniversalTime().AddSeconds(-60))); Write-Host "Worker registration: $($state.status) | Last heartbeat: $($state.lastHeartbeat) | Active job: $(if ($state.currentJobId) {$state.currentJobId} else {'none'})" }
    catch { Write-Host "Worker registration/heartbeat: UNKNOWN - $($_.Exception.Message)" }
    Write-Host "Configured concurrency: $(if ($config.Worker.WORKER_CONCURRENCY) {$config.Worker.WORKER_CONCURRENCY} else {'NOT CONFIGURED'})"
    try { $event = Request-Json "$($config.Api)/event/status" @{} 1; $bracket = Request-Json "$($config.Api)/tournament/status" @{} 1; Write-Host "Competition mode: $($event.mode) | Tournament: $($bracket.status)" }
    catch { Write-Host 'Competition: UNKNOWN (public status unavailable)' }
    Write-Host 'Queued/running counts: NOT EXPOSED without an admin session; inspect Admin -> Operations.'
    Write-Host "Overall: $(if ($cloudReady -and $localReady -and $heartbeatReady) {'READY'} else {'NOT READY / UNVERIFIED'})"
    Write-Host '=================================================='
}

function Open-Admin {
    $config = Cloud-Config
    if (-not $config.Frontend) { throw "Set frontendUrl in $localFile first." }
    Start-Process -FilePath ($config.Frontend + '/admin')
    Write-Host "Opened $($config.Frontend)/admin"
}

function Show-Logs {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logs = @(Get-ChildItem -LiteralPath $logDir -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
    if (-not $logs.Count) { Write-Host "No evaluator logs yet. Folder: $logDir"; return }
    $logs | Select-Object -First 8 Name,LastWriteTime,Length | Format-Table -AutoSize
    $choice = Read-Host 'R = recent log entries, O = open folder, Enter = menu'
    if ($choice -eq 'O') { Start-Process -FilePath explorer.exe -ArgumentList ('"' + $logDir + '"') }
    if ($choice -eq 'R') { Get-Content -LiteralPath $logs[0].FullName -Tail 80 }
    $old = @(Get-ChildItem -LiteralPath $logDir -File | Sort-Object LastWriteTime -Descending | Select-Object -Skip 20)
    foreach ($file in $old) { if ($file.LastWriteTime -lt (Get-Date).AddDays(-14)) { Remove-Item -LiteralPath $file.FullName } }
    Write-Host 'Cloud logs require Render Dashboard authentication.'
}

function Run-Benchmark {
    if ((Get-WorkerProcess) -or @(Find-OtherWorker).Count) { throw 'Stop the live evaluator before benchmarking; active jobs may be running.' }
    $config = Cloud-Config
    Test-Docker
    $null = Test-Image $config
    $levels = Read-Host 'Concurrency levels (comma separated, default 1,2,4,6,8)'
    if (-not $levels) { $levels = '1,2,4,6,8' }
    if ($levels -notmatch '^\d{1,2}(,\d{1,2})*$') { throw 'Enter numeric levels such as 1,2,4.' }
    $games = Read-Host 'Real games per level (default 8)'
    if (-not $games) { $games = '8' }
    if ($games -notmatch '^\d+$' -or [int]$games -lt 1 -or [int]$games -gt 100) { throw 'Games must be 1..100.' }
    if ((Read-Host 'These run real isolated Docker matches. Type BENCHMARK to continue') -ne 'BENCHMARK') { Write-Host 'Benchmark cancelled.'; return }
    $python = Join-Path $package '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Evaluator Python environment missing. Choose First-Time Setup.' }
    & $python (Join-Path $PSScriptRoot 'benchmark.py') --levels $levels --games $games
    if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed; review the error above.' }
    $report = @(Get-Content -LiteralPath (Join-Path $package 'benchmark.json') -Raw | ConvertFrom-Json)
    $stable = @($report | Where-Object { $_.completed -eq $_.games -and @($_.failures).Count -eq 0 } | Sort-Object jobsPerMinute -Descending)
    Write-Host "JSON report: $(Join-Path $package 'benchmark.json')"
    if ($stable.Count) { Write-Host "Best measured stable concurrency: $($stable[0].concurrency) ($($stable[0].jobsPerMinute) games/minute). Production setting was not changed." }
}

function Deploy-Site {
    $config = Cloud-Config
    $yaml = Get-Content -LiteralPath (Join-Path $repo 'render.yaml') -Raw
    $branches = @([regex]::Matches($yaml, '(?m)^\s*branch:\s*([^\s#]+)') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    $plans = @([regex]::Matches($yaml, '(?m)^\s*plan:\s*([^\s#]+)') | ForEach-Object { $_.Groups[1].Value })
    if ($branches.Count -ne 1 -or $plans.Count -ne 1 -or $plans[0] -ne 'free' -or $yaml -notmatch 'runtime: static') { throw 'Blueprint branch or Free plan configuration is unexpected; review render.yaml before deployment.' }
    $branch = $branches[0]
    $remote = (& git -C $repo remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or $remote -notmatch '^https://github\.com/OmKumar-2007/Kaggriculture(\.git)?$') { throw 'Origin is not the configured FarmCraft repository.' }
    $remoteSha = (& git -C $repo ls-remote origin "refs/heads/$branch").Split("`t")[0]
    if ($LASTEXITCODE -ne 0 -or -not $remoteSha) { throw "Could not verify origin/$branch. Check Git connectivity." }
    $localBranch = (& git -C $repo branch --show-current).Trim()
    $localSha = (& git -C $repo rev-parse HEAD).Trim()
    $changes = @(& git -C $repo status --porcelain)
    Write-Host "Repository: $remote | Render branch: $branch | Current branch: $localBranch"
    Write-Host "Render branch commit: $($remoteSha.Substring(0,7)) | Local HEAD: $($localSha.Substring(0,7))"
    if ($changes.Count) { Write-Warning 'Uncommitted changes are not deployable; review and push them separately.'; return }
    if ($localBranch -ne $branch -or $localSha -ne $remoteSha) { Write-Warning 'This checkout is not the exact pushed Render branch. No push or deployment will be triggered.'; return }
    if (-not $config.Local.apiDeployHook -or -not $config.Local.webDeployHook) {
        Write-Host "No deploy hooks configured in $localFile. Existing Git auto-deploy may run after a push."
        Write-Host 'For initial setup, open: https://dashboard.render.com/blueprint/new?repo=https://github.com/OmKumar-2007/Kaggriculture'
        Write-Host 'Confirm only a Free web service and Free static site, then set sync:false variables securely in Render.'
        Start-Process -FilePath 'https://dashboard.render.com/'
        return
    }
    foreach ($hook in @($config.Local.apiDeployHook,$config.Local.webDeployHook)) {
        if (([uri]$hook).Scheme -ne 'https' -or ([uri]$hook).Host -ne 'api.render.com') { throw 'Deploy hooks must be HTTPS URLs from api.render.com.' }
    }
    if ((Read-Host "Deploy pushed $branch commit $($remoteSha.Substring(0,7))? Type DEPLOY") -ne 'DEPLOY') { Write-Host 'Deployment cancelled.'; return }
    foreach ($name in @('apiDeployHook','webDeployHook')) {
        try { $null = Invoke-WebRequest -Method Post -Uri $config.Local[$name] -UseBasicParsing -TimeoutSec 30; Write-Host "$name accepted by Render (deployment completion not yet confirmed)." }
        catch { throw "$name trigger failed. Check Render Dashboard and the local hook configuration. The hook URL is intentionally hidden." }
    }
    for ($i=0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 10
        try { $null = Check-Cloud $config; Write-Host 'Live endpoints respond and dependencies are ready. Confirm target commit in Render Dashboard.'; return } catch { if ($i -eq 11) { Write-Warning $_.Exception.Message } }
    }
    Write-Warning 'Render accepted the triggers, but completion was not confirmed within two minutes. Check Render Dashboard.'
}

function Invoke-Action($name) {
    switch ($name) {
        'Setup' { Show-Setup }
        'Start' { Start-Evaluator }
        'Deploy' { Deploy-Site }
        'EventDay' { $config = Cloud-Config; $null = Check-Cloud $config; Start-Evaluator; Show-Health; Open-Admin }
        'Health' { Show-Health }
        'Stop' { Stop-Evaluator }
        'Logs' { Show-Logs }
        'Benchmark' { Run-Benchmark }
        'Admin' { Open-Admin }
    }
}

if ($Action -ne 'Menu') {
    try { Invoke-Action $Action; exit 0 } catch { Write-Error $_.Exception.Message; exit 1 }
}
while ($true) {
    Clear-Host
    $config = Cloud-Config
    $process = Get-WorkerProcess
    Write-Host '==================================================='
    Write-Host '                   FARMCRAFT'
    Write-Host '              EVENT SERVER MANAGER'
    Write-Host '==================================================='
    Write-Host " Cloud:     $(if ($config.Api) {$config.Api} else {'NOT CONFIGURED'})"
    Write-Host " Evaluator: $(if ($process) {"RUNNING ($($process.ProcessId))"} else {'STOPPED'})"
    Write-Host ' Docker:    Check with Option 5'
    Write-Host ''
    Write-Host ' [1] First-Time Setup'
    Write-Host ' [2] Start Evaluation Server'
    Write-Host ' [3] Deploy / Update Render Website'
    Write-Host ' [4] Start Evaluator + Check Deployment'
    Write-Host ' [5] Check Complete System Health'
    Write-Host ' [6] Stop Evaluation Server'
    Write-Host ' [7] View Logs'
    Write-Host ' [8] Run Evaluator Benchmark'
    Write-Host ' [9] Open Admin Dashboard'
    Write-Host ' [0] Exit'
    $selected = Read-Host 'Select an option'
    if ($selected -eq '0') { exit 0 }
    $map = @{ '1'='Setup'; '2'='Start'; '3'='Deploy'; '4'='EventDay'; '5'='Health'; '6'='Stop'; '7'='Logs'; '8'='Benchmark'; '9'='Admin' }
    if (-not $map.ContainsKey($selected)) { Write-Host 'Choose 0-9.'; Start-Sleep -Seconds 1; continue }
    try { Invoke-Action $map[$selected] }
    catch { Write-Host "`nFAILED: $($_.Exception.Message)" -ForegroundColor Red }
    $null = Read-Host 'Press Enter to return to menu'
}
