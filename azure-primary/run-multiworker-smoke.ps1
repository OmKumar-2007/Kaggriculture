param([ValidateRange(60,900)][int]$TimeoutSeconds = 300)

$ErrorActionPreference = 'Stop'
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$profileRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-profiles'
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$jobIds = @()

function Admin($method, $path, $body = $null) {
    $args = @{Method=$method;Uri="$base/api/admin$path";WebSession=$session;
        Headers=@{'x-admin-csrf'=$script:csrf};TimeoutSec=45}
    if ($null -ne $body) {
        $args.Body = $body | ConvertTo-Json -Depth 8 -Compress
        $args.ContentType = 'application/json'
    }
    Invoke-RestMethod @args
}
function Assert-Closed($event) {
    if ($event.mode -ne 'MAINTENANCE' -or $event.registrationsEnabled -or
        $event.uploadsEnabled -or $event.sandboxEnabled -or $event.officialEnabled -or
        $event.tournamentEnabled) {
        throw 'Staging public participant gates are not all closed.'
    }
}

$secure = Get-Content -LiteralPath (Join-Path $profileRoot 'phase4-admin.dpapi') | ConvertTo-SecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $login = Invoke-RestMethod -Method Post -Uri "$base/api/admin/login" -Body (@{password=$password}|ConvertTo-Json) `
        -ContentType application/json -WebSession $session -TimeoutSec 45
    $script:csrf = $login.csrfToken
} finally {
    $password = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secure.Dispose()
}

try {
    $ready = Invoke-RestMethod "$base/ready" -TimeoutSec 45
    if ($ready.status -ne 'ready') { throw 'Staging API is not ready.' }
    Assert-Closed (Admin GET '/event')
    $competition = Admin GET '/competition'
    if ($competition.phase -ne 'QUALIFICATION_OPEN' -or $competition.referencePool.Count -ne 3 -or
        $competition.evaluationConfig.seeds.Count -ne 1 -or $competition.evaluationConfig.sides.Count -ne 2) {
        throw 'Frozen six-game staging qualification configuration has changed.'
    }
    $workers = (Admin GET '/remote-workers').workers
    $slots = @($workers | Where-Object { $_.name -in @('farmcraft-staging-01','farmcraft-staging-02') })
    if ($slots.Count -ne 2 -or @($slots | Where-Object status -ne 'idle').Count) {
        throw 'Both staging-only workers must be idle before the smoke test.'
    }
    $references = (Admin GET '/reference-bots').bots
    foreach ($id in @($competition.referencePool | ForEach-Object { $_.id })) {
        if (-not (@($references | Where-Object id -eq $id).Count)) { throw "Frozen reference $id is missing." }
        $queued = Admin POST "/reference-bots/$id/test"
        $jobIds += $queued.job.id
    }
    if ($jobIds.Count -ne 3) { throw 'Exactly three reference jobs must be queued.' }
    Write-Host "Queued three existing-reference tests: $($jobIds -join ', ')"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Seconds 5
        $jobs = @($jobIds | ForEach-Object { Admin GET "/jobs/$_" })
        $terminal = @($jobs | Where-Object { $_.status -in @('completed','failed','timeout','cancelled') })
    } while ($terminal.Count -lt 3 -and (Get-Date) -lt $deadline)
    if ($terminal.Count -ne 3) { throw 'Staging smoke jobs did not all reach terminal state in time.' }
    if (@($jobs | Where-Object status -ne 'completed').Count) { throw 'At least one staging smoke job failed.' }
    $assigned = @($jobs | ForEach-Object { $_.worker } | Sort-Object -Unique)
    if ($assigned.Count -lt 2) { throw 'Jobs completed, but two distinct workers did not claim them.' }
    Assert-Closed (Admin GET '/event')
    [pscustomobject]@{jobs=$jobIds;distinctWorkers=$assigned.Count;workerIds=$assigned;
        completed=3;publicGates='closed'} | ConvertTo-Json -Depth 4
} finally {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'staging-workers.ps1') -Action Drain -Count 2
    Start-Sleep -Seconds 10
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'staging-workers.ps1') -Action Status -Count 2
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'staging-workers.ps1') -Action Revoke -Count 2
}
