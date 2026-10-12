param([ValidateRange(60,900)][int]$TimeoutSeconds = 300)
$ErrorActionPreference = 'Stop'
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$profileRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-profiles'
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

function Admin($method, $path, $body = $null) {
    $args = @{Method=$method;Uri="$base/api/admin$path";WebSession=$session;
        Headers=@{'x-admin-csrf'=$script:csrf};TimeoutSec=45}
    if ($null -ne $body) {
        $args.Body = $body | ConvertTo-Json -Depth 8 -Compress
        $args.ContentType = 'application/json'
    }
    Invoke-RestMethod @args
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

$ready = Invoke-RestMethod "$base/ready" -TimeoutSec 45
if ($ready.status -ne 'ready') { throw 'Staging API not ready.' }
$event = Admin GET '/event'
if ($event.mode -ne 'MAINTENANCE' -or $event.registrationsEnabled -or $event.uploadsEnabled -or
    $event.sandboxEnabled -or $event.officialEnabled -or $event.tournamentEnabled) {
    throw 'Staging participant gates are open; refusing smoke.'
}
$competition = Admin GET '/competition'
if ($competition.phase -ne 'QUALIFICATION_OPEN' -or @($competition.referencePool).Count -ne 3) {
    throw 'Frozen staging qualification configuration changed.'
}
$workers = (Admin GET '/remote-workers').workers
$names = @('farmcraft-kr-01','farmcraft-kr-02','farmcraft-id-01','farmcraft-id-02')
$online = @($workers | Where-Object { $_.name -in $names -and $_.status -eq 'idle' -and $_.availableSlots -ge 1 })
if ($online.Count -lt 4) { throw "Expected four idle new workers, found $($online.Count)." }
$referenceId = $competition.referencePool[0].id
$queued = Admin POST "/reference-bots/$referenceId/test"
$jobId = $queued.job.id
if (-not $jobId) { throw 'Reference test did not return a job ID.' }
Write-Host "Queued staging reference smoke job $jobId"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Seconds 5
    $job = Admin GET "/jobs/$jobId"
} while ($job.status -notin @('completed','failed','timeout','cancelled') -and (Get-Date) -lt $deadline)
if ($job.status -ne 'completed') { throw "Smoke job $jobId ended with status $($job.status)." }
[pscustomobject]@{jobId=$jobId;status=$job.status;worker=$job.worker;attempt=$job.attempt;
    resultKeys=@($job.result.PSObject.Properties.Name);eventMode=(Admin GET '/event').mode;
    finishedAt=$job.finishedAt} | ConvertTo-Json -Depth 5
