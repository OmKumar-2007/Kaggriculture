param([int]$TimeoutSeconds = 900)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$local = Join-Path $root 'config/local-profiles'
$profile = Join-Path $local 'staging-worker.env'
$credential = Join-Path $local 'staging-worker.credentials.json'
$drainMarker = [System.IO.Path]::ChangeExtension($credential, 'drain')
$python = Join-Path $root 'farmcraft-evaluator/.venv/Scripts/python.exe'
$workerScript = Join-Path $root 'farmcraft-evaluator/app/worker.py'
$worker = $null
$workerId = $null
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$csrf = $null
$jobIds = [System.Collections.Generic.List[string]]::new()

function Assert-Closed($event) {
    if ($event.mode -ne 'MAINTENANCE' -or $event.registrationsEnabled -or
        $event.uploadsEnabled -or $event.sandboxEnabled -or $event.officialEnabled -or
        $event.tournamentEnabled) { throw 'Staging participant controls are not fully closed.' }
}

function Admin($method, $path, $body = $null) {
    $args = @{ Method=$method; Uri="$base/api/admin$path"; WebSession=$session; Headers=@{'x-admin-csrf'=$csrf}; TimeoutSec=90 }
    if ($null -ne $body) {
        $args.Body = $body | ConvertTo-Json -Depth 12 -Compress
        $args.ContentType = 'application/json'
    }
    Invoke-RestMethod @args
}

function Upload($path, $file, $fields) {
    $form = @{ file = Get-Item -LiteralPath $file }
    foreach ($key in $fields.Keys) { $form[$key] = [string]$fields[$key] }
    Invoke-RestMethod -Method Post -Uri "$base/api/admin$path" -WebSession $session -Headers @{'x-admin-csrf'=$csrf} -Form $form -TimeoutSec 90
}

function Wait-StagingJob($id, $label, $seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    do {
        $job = Admin 'GET' "/jobs/$id"
        if ($job.status -in @('completed','failed','timeout','cancelled')) {
            Write-Host "$label status=$($job.status) id=$id"
            if ($job.status -ne 'completed') { throw "$label ended $($job.status); see staging Admin job $id." }
            return $job
        }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)
    throw "$label timed out waiting for job $id; inspect it before retrying."
}

if (-not (Test-Path -LiteralPath $profile) -or -not (Test-Path -LiteralPath $python)) {
    throw 'Dedicated staging worker profile or Python environment is missing.'
}
if (Test-Path -LiteralPath $credential) { throw 'A staging worker credential already exists; inspect it before registering another.' }
if ((docker info --format '{{.ServerVersion}}' 2>$null) -eq $null) { throw 'Docker is unavailable.' }
if (-not (docker image inspect nitw-farm-ai-evaluator:2026.10.12 --format '{{.Id}}' 2>$null)) {
    throw 'The approved evaluator image is missing.'
}
$configHash = (Get-FileHash -Algorithm SHA256 (Join-Path $root 'config/evaluation.json')).Hash.ToLowerInvariant()

$secure = Get-Content -LiteralPath (Join-Path $local 'phase4-admin.dpapi') | ConvertTo-SecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $login = Invoke-RestMethod -Method Post -Uri "$base/api/admin/login" -Body (@{password=$password}|ConvertTo-Json) -ContentType 'application/json' -WebSession $session -TimeoutSec 90
    $csrf = $login.csrfToken
} finally {
    $password = $null
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secure.Dispose()
}

try {
    $ready = Invoke-RestMethod "$base/ready"
    if ($ready.status -ne 'ready') { throw 'Staging API is not ready.' }
    $version = Invoke-RestMethod "$base/api/remote-workers/version"
    if ($version.evaluatorVersion -ne '2026.10.12' -or $version.evaluationConfigSha256 -ne $configHash -or $version.evaluatorMode -ne 'LOCAL') {
        throw 'Staging evaluator version, mode, or configuration hash differs from the local worker.'
    }
    Assert-Closed (Admin 'GET' '/event')
    $competition = Admin 'GET' '/competition'
    if ($competition.phase -ne 'SETUP') { throw 'Staging competition is no longer in SETUP.' }
    if ((Admin 'GET' '/reference-bots').bots.Count -ne 0) { throw 'Staging references already exist.' }
    if ((Admin 'GET' '/jobs?limit=10').jobs.Count -ne 0) { throw 'Staging jobs already exist.' }
    $workerState = Admin 'GET' '/remote-workers'
    if ($workerState.workers.Count -ne 0 -or -not $workerState.registrationEnabled) { throw 'Worker registry differs from approved preflight.' }

    $registration = Admin 'POST' '/remote-workers/registration'
    $identity = Invoke-RestMethod -Method Post -Uri "$base/api/remote-workers/register" -Body (@{
        token=$registration.token; name='FarmCraft Staging Laptop 1'; version='2026.10.12'; maxConcurrency=1
    }|ConvertTo-Json) -ContentType 'application/json' -TimeoutSec 90
    $registration = $null
    $workerId = $identity.workerId
    $pending = "$credential.pending"
    $identity | ConvertTo-Json -Compress | Set-Content -LiteralPath $pending -Encoding utf8
    & icacls $pending /inheritance:r /grant:r "${env:USERNAME}:F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not protect the staging worker credential.' }
    Move-Item -LiteralPath $pending -Destination $credential
    $identity = $null
    Write-Host "Registered one staging worker id=$workerId"

    $env:FARMCRAFT_WORKER_ENV_FILE = $profile
    $env:FARMCRAFT_WORKER_CREDENTIAL_FILE = $credential
    $stdout = Join-Path $local 'staging-worker.stdout.log'
    $stderr = Join-Path $local 'staging-worker.stderr.log'
    $worker = Start-Process -FilePath $python -ArgumentList $workerScript -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Start-Sleep -Seconds 5
    if ($worker.HasExited) { throw 'The staging worker exited during startup; inspect local worker logs.' }
    Write-Host "Local worker started pid=$($worker.Id)"

    $referenceRoot = Join-Path $local 'checkpoint-b-reference-sources'
    New-Item -ItemType Directory -Path (Join-Path $referenceRoot 'crop'), (Join-Path $referenceRoot 'animal') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $root 'backend/private_benchmarks/baseline_alpha.py') -Destination (Join-Path $referenceRoot 'crop/agent.py')
    Copy-Item -LiteralPath (Join-Path $root 'backend/private_benchmarks/baseline_beta.py') -Destination (Join-Path $referenceRoot 'animal/agent.py')
    $sources = @(
        @{name='Starter'; path=(Join-Path $root 'contestant_starter/agent.py')},
        @{name='Crop baseline'; path=(Join-Path $referenceRoot 'crop/agent.py')},
        @{name='Animal baseline'; path=(Join-Path $referenceRoot 'animal/agent.py')}
    )
    $bots = @()
    foreach ($source in $sources) {
        $bot = Upload '/reference-bots' $source.path @{displayName=$source.name; category='staging checkpoint B'; description='Isolated six-game evaluator verification'}
        $bots += $bot
        $test = Admin 'POST' "/reference-bots/$($bot.id)/test"
        $jobIds.Add($test.job.id)
        $null = Wait-StagingJob $test.job.id "Reference $($bot.id)" $TimeoutSeconds
        $row = (Admin 'GET' '/reference-bots').bots | Where-Object id -eq $bot.id
        if ($row.testStatus -ne 'passed' -or $row.validationStatus -ne 'valid') { throw "Reference $($bot.id) did not pass validation and real testing." }
        $null = Admin 'PUT' "/reference-bots/$($bot.id)" @{selected=$true;enabled=$true}
    }
    Write-Host "Three real reference tests passed: $($bots.id -join ',')"

    $settings = (Admin 'GET' '/competition').settings
    $null = Admin 'PUT' '/competition/settings' @{
        qualifierCount=$settings.qualifierCount; registrationCapacity=$settings.registrationCapacity
        officialAttemptLimit=1; referenceCount=3; qualificationSeedCount=1
        tieReplayLimit=$settings.tieReplayLimit
    }
    $fixture = Upload '/staging-fixture/upload' (Join-Path $root 'contestant_starter/agent.py') @{confirmation='CREATE STAGING FIXTURE'}
    Write-Host "Fixture uploaded team=$($fixture.team) submission=$($fixture.submissionId)"
    $snapshot = Admin 'POST' '/competition/start-qualification' @{confirmation='START QUALIFICATION';openAccess=$false}
    if ($snapshot.phase -ne 'QUALIFICATION_OPEN' -or $snapshot.referencePool.Count -ne 3 -or $snapshot.evaluationConfig.seeds.Count -ne 1) {
        throw 'Frozen qualification snapshot is not the approved six-game configuration.'
    }
    Assert-Closed (Admin 'GET' '/event')
    $official = Admin 'POST' '/staging-fixture/queue-official' @{confirmation='QUEUE SIX STAGING GAMES'}
    $jobIds.Add($official.jobId)
    $result = Wait-StagingJob $official.jobId 'Six-game official fixture' $TimeoutSeconds
    if ($result.result.games -ne 6 -or $result.result.matchResults.Count -ne 6) {
        throw 'Official job completed without six recorded match results.'
    }
    $replays = @($result.result.matchResults | ForEach-Object { $_.replayId })
    if (($replays | Select-Object -Unique).Count -ne 6 -or $replays -contains $null) {
        throw 'Official job did not produce six distinct replay IDs.'
    }
    Write-Host "SUCCESS officialJob=$($official.jobId) games=$($result.result.games) rating=$($result.result.rating) distinctReplays=6"
} catch {
    Write-Host "CHECKPOINT B STOPPED: $($_.Exception.Message)"
    throw
} finally {
    if ($workerId) {
        try { $null = Admin 'POST' "/remote-workers/$workerId/drain" @{confirmation='DRAIN'} } catch { Write-Host 'Worker drain request failed; inspect staging worker.' }
    }
    if ($worker -and -not $worker.HasExited) {
        New-Item -ItemType File -Path $drainMarker -Force | Out-Null
        try { Wait-Process -Id $worker.Id -Timeout 150 -ErrorAction Stop } catch { Write-Host 'Worker process did not exit after drain; inspect it before stopping.' }
        Remove-Item -LiteralPath $drainMarker -ErrorAction SilentlyContinue
    }
    if ($workerId) {
        try { $null = Admin 'POST' "/remote-workers/$workerId/revoke" @{confirmation='REVOKE'}; Write-Host "Revoked staging worker id=$workerId" }
        catch { Write-Host 'Worker revocation failed; inspect staging Admin immediately.' }
    }
    try { Assert-Closed (Admin 'GET' '/event'); Write-Host 'Participant controls remain closed.' }
    catch { Write-Host 'Participant controls require inspection.' }
    Write-Host "Jobs created: $($jobIds -join ',')"
}
