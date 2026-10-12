param(
    [ValidateSet('Inspect','Prepare','Register','Start','Status','Drain','Stop','Revoke','Logs','Export')]
    [string]$Action = 'Inspect',
    [ValidateRange(1,10)][int]$Count = 2,
    [ValidateRange(1,10)][int]$FirstSlot = 1,
    [ValidateRange(1,10)][int]$Slot = 1
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$local = Join-Path $root 'config/local-profiles'
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$python = Join-Path $root 'farmcraft-evaluator/.venv/Scripts/python.exe'
$workerScript = Join-Path $root 'farmcraft-evaluator/app/worker.py'
$image = 'nitw-farm-ai-evaluator:2026.10.12'

function Slot-Path([int]$number, [string]$kind) {
    Join-Path $local ("staging-worker-{0:D2}.{1}" -f $number, $kind)
}
function Assert-Compatibility {
    $ready = Invoke-RestMethod "$base/ready" -TimeoutSec 30
    $version = Invoke-RestMethod "$base/api/remote-workers/version" -TimeoutSec 30
    $localHash = (Get-FileHash (Join-Path $root 'config/evaluation.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ready.status -ne 'ready' -or $version.evaluatorVersion -ne '2026.10.12' -or
        $version.evaluationConfigSha256 -ne $localHash -or $version.evaluatorMode -ne 'LOCAL') {
        throw 'Staging readiness, evaluator version, mode or configuration hash mismatch.'
    }
    return $version
}
function Assert-LocalCapacity([int]$slots) {
    if (-not (Test-Path -LiteralPath $python)) { throw 'Install dedicated worker dependencies first.' }
    if ((& docker info --format '{{.ServerVersion}}' 2>$null) -eq $null) { throw 'Docker is unavailable.' }
    if (-not (& docker image inspect $image --format '{{.Id}}' 2>$null)) { throw "Evaluator image $image is absent." }
    $logical = [Environment]::ProcessorCount
    $memoryGiB = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
    $active = @(1..10 | ForEach-Object { Local-Status $_ } | Where-Object running).Count
    $total = $slots + $active
    if ($total -gt [math]::Max(1,[math]::Floor($logical / 2)) -or $memoryGiB -lt (4 + 1.5 * $total)) {
        throw "Requested $slots more one-job processes exceed conservative host limits ($active active, $logical logical CPUs, $memoryGiB GiB RAM)."
    }
}
function New-AdminSession {
    $protected = Join-Path $local 'phase4-admin.dpapi'
    if (-not (Test-Path -LiteralPath $protected)) { throw 'Staging Admin DPAPI archive is missing.' }
    $secure = Get-Content -LiteralPath $protected | ConvertTo-SecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $password = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $login = Invoke-RestMethod -Method Post -Uri "$base/api/admin/login" -Body (@{password=$password}|ConvertTo-Json) -ContentType application/json -WebSession $session -TimeoutSec 30
        return @{session=$session;csrf=$login.csrfToken}
    } finally {
        $password = $null
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        $secure.Dispose()
    }
}
function Admin($auth, $method, $path, $body = $null) {
    $args = @{Method=$method;Uri="$base/api/admin$path";WebSession=$auth.session;
        Headers=@{'x-admin-csrf'=$auth.csrf};TimeoutSec=30}
    if ($null -ne $body) { $args.Body=$body|ConvertTo-Json -Depth 8 -Compress; $args.ContentType='application/json' }
    Invoke-RestMethod @args
}
function Local-Status([int]$number) {
    $pidPath = Slot-Path $number 'pid'
    $processId = if (Test-Path -LiteralPath $pidPath) { [int](Get-Content -LiteralPath $pidPath -Raw) } else { 0 }
    $process = if ($processId) { Get-Process -Id $processId -ErrorAction SilentlyContinue } else { $null }
    [pscustomobject]@{slot=$number;worker=("farmcraft-staging-{0:D2}" -f $number);
        processId=$processId;running=[bool]$process;
        registered=(Test-Path -LiteralPath (Slot-Path $number 'credentials.json'));
        profile=(Test-Path -LiteralPath (Slot-Path $number 'env'))}
}

if ($FirstSlot + $Count - 1 -gt 10) { throw 'Slot range exceeds 10.' }
if ($Action -in @('Inspect','Prepare','Register','Start')) { $null = Assert-Compatibility }
switch ($Action) {
    'Inspect' {
        [pscustomobject]@{environment='AZURE STAGING';api=$base;
            localCpus=[Environment]::ProcessorCount;
            dockerAvailable=[bool](& docker info --format '{{.ServerVersion}}' 2>$null);
            evaluatorImage=$image} | Format-List
        $FirstSlot..($FirstSlot+$Count-1) | ForEach-Object { Local-Status $_ } | Format-Table
    }
    'Prepare' {
        Assert-LocalCapacity $Count
        New-Item -ItemType Directory -Path $local -Force | Out-Null
        $template = Join-Path $local 'staging-worker.env'
        if (-not (Test-Path -LiteralPath $template)) { throw 'Staging worker profile template is missing.' }
        for ($number=$FirstSlot; $number -lt $FirstSlot+$Count; $number++) {
            $profile = Slot-Path $number 'env'
            if (Test-Path -LiteralPath $profile) { continue }
            $settings = (Get-Content -LiteralPath $template -Raw) -replace '(?m)^WORKER_NAME=.*$',("WORKER_NAME=farmcraft-staging-{0:D2}" -f $number)
            $settings = $settings -replace '(?m)^WORKER_CONCURRENCY=.*$', 'WORKER_CONCURRENCY=1'
            [IO.File]::WriteAllText($profile, $settings, [Text.UTF8Encoding]::new($false))
            & icacls $profile /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not protect profile for slot $number." }
        }
        Write-Host "Prepared $Count isolated staging profiles. No worker registered or started."
    }
    'Register' {
        $profile = Slot-Path $Slot 'env'
        $credential = Slot-Path $Slot 'credentials.json'
        if (-not (Test-Path -LiteralPath $profile) -or (Test-Path -LiteralPath $credential)) {
            throw 'Prepare the slot first; an existing credential will never be overwritten.'
        }
        $auth = New-AdminSession
        $registry = Admin $auth 'GET' '/remote-workers'
        if (-not $registry.registrationEnabled) { throw 'Staging worker registration is disabled.' }
        $name = "farmcraft-staging-{0:D2}" -f $Slot
        if (@($registry.workers | Where-Object name -eq $name).Count) { throw 'This worker name already exists in staging; inspect/revoke it first.' }
        $token = Admin $auth 'POST' '/remote-workers/registration'
        try {
            $identity = Invoke-RestMethod -Method Post -Uri "$base/api/remote-workers/register" -Body (@{
                token=$token.token;name=$name;version='2026.10.12';maxConcurrency=1;
                configSha256=(Get-FileHash (Join-Path $root 'config/evaluation.json') -Algorithm SHA256).Hash.ToLowerInvariant()
            }|ConvertTo-Json) -ContentType application/json -TimeoutSec 30
        } finally { $token = $null }
        $pending = "$credential.pending"
        [IO.File]::WriteAllText($pending, ($identity | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
        & icacls $pending /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not protect the worker credential.' }
        Move-Item -LiteralPath $pending -Destination $credential
        Write-Host "Registered $name with a distinct protected credential."
    }
    'Start' {
        Assert-LocalCapacity $Count
        # A developer shell can contain a local API override. Profiles are the
        # authority for these staging processes; never inherit those overrides.
        foreach ($name in @('FARMCRAFT_API_URL','WORKER_NAME','WORKER_CONCURRENCY',
                'WORKER_HEARTBEAT_SECONDS','WORKER_POLL_SECONDS','EVALUATION_TIMEOUT_SECONDS',
                'EVALUATION_MEMORY_MB','EVALUATION_CPU_LIMIT','EVALUATION_PIDS_LIMIT',
                'EVALUATOR_IMAGE')) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        }
        for ($number=$FirstSlot; $number -lt $FirstSlot+$Count; $number++) {
            $state = Local-Status $number
            if ($state.running) { throw "Worker slot $number is already running." }
            if (-not $state.registered -or -not $state.profile) { throw "Worker slot $number is not prepared and registered." }
        }
        for ($number=$FirstSlot; $number -lt $FirstSlot+$Count; $number++) {
            $env:FARMCRAFT_WORKER_ENV_FILE = Slot-Path $number 'env'
            $env:FARMCRAFT_WORKER_CREDENTIAL_FILE = Slot-Path $number 'credentials.json'
            $drainMarker = Slot-Path $number 'credentials.drain'
            if (Test-Path -LiteralPath $drainMarker) { Remove-Item -LiteralPath $drainMarker }
            $process = Start-Process -FilePath $python -ArgumentList $workerScript -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Slot-Path $number 'stdout.log') -RedirectStandardError (Slot-Path $number 'stderr.log')
            $process.Id | Set-Content -LiteralPath (Slot-Path $number 'pid')
            Write-Host "Started staging worker $number as process $($process.Id)."
        }
    }
    'Status' {
        $auth = New-AdminSession
        $remote = Admin $auth 'GET' '/remote-workers'
        $FirstSlot..($FirstSlot+$Count-1) | ForEach-Object {
            $localState = Local-Status $_
            $remoteState = $remote.workers | Where-Object name -eq $localState.worker | Select-Object -First 1
            [pscustomobject]@{slot=$_;name=$localState.worker;process=$localState.processId;
                running=$localState.running;remoteStatus=$remoteState.status;
                active=$remoteState.activeJobs;available=$remoteState.availableSlots;
                completed=$remoteState.jobsCompleted;failed=$remoteState.jobsFailed;
                heartbeat=$remoteState.lastHeartbeat}
        } | Format-Table
    }
    { $_ -in @('Drain','Stop','Revoke') } {
        $auth = if ($Action -in @('Drain','Revoke')) { New-AdminSession } else { $null }
        $remote = if ($auth) { Admin $auth 'GET' '/remote-workers' } else { $null }
        for ($number=$FirstSlot; $number -lt $FirstSlot+$Count; $number++) {
            $name = "farmcraft-staging-{0:D2}" -f $number
            $row = $remote.workers | Where-Object name -eq $name | Select-Object -First 1
            if ($Action -eq 'Drain' -and $row) {
                $null = Admin $auth 'POST' "/remote-workers/$($row.id)/drain" @{confirmation='DRAIN'}
            }
            if ($Action -in @('Drain','Stop')) {
                $marker = Slot-Path $number $(if ($Action -eq 'Drain') {'credentials.drain'} else {'credentials.stop'})
                [IO.File]::WriteAllText($marker, $Action.ToLowerInvariant())
            }
            if ($Action -eq 'Revoke' -and $row) {
                $null = Admin $auth 'POST' "/remote-workers/$($row.id)/revoke" @{confirmation='REVOKE'}
            }
            Write-Host "$Action requested for $name."
        }
    }
    'Logs' {
        $path = Slot-Path $Slot 'stdout.log'
        if (-not (Test-Path -LiteralPath $path)) { throw 'No worker log for this slot.' }
        Get-Content -LiteralPath $path -Tail 40
        $errorPath = Slot-Path $Slot 'stderr.log'
        if (Test-Path -LiteralPath $errorPath) { Get-Content -LiteralPath $errorPath -Tail 20 }
    }
    'Export' {
        $auth = New-AdminSession
        $workers = Admin $auth 'GET' '/remote-workers'
        $jobs = Admin $auth 'GET' '/jobs?limit=100'
        $report = @{environment='AZURE STAGING';generatedAt=(Get-Date).ToString('o');
            workers=$workers.workers;jobs=$jobs.jobs}
        $path = Join-Path $local ("staging-operations-{0:yyyyMMdd-HHmmss}.json" -f (Get-Date))
        $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding utf8
        Write-Host "Operational report saved to ignored local profile: $path"
    }
}
