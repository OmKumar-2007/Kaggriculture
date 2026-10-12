$ErrorActionPreference = 'Stop'
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$secure = Get-Content -LiteralPath (Join-Path $root 'config/local-profiles/phase4-admin.dpapi') | ConvertTo-SecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    $null = Invoke-RestMethod -Method Post -Uri "$base/api/admin/login" -Body (@{password=$password}|ConvertTo-Json) `
        -ContentType application/json -WebSession $session -TimeoutSec 45
} finally {
    $password = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secure.Dispose()
}
$ready = Invoke-RestMethod "$base/ready" -TimeoutSec 45
$event = Invoke-RestMethod "$base/api/admin/event" -WebSession $session -TimeoutSec 45
$competition = Invoke-RestMethod "$base/api/admin/competition" -WebSession $session -TimeoutSec 45
$metrics = Invoke-RestMethod "$base/api/admin/metrics" -WebSession $session -TimeoutSec 45
$workers = Invoke-RestMethod "$base/api/admin/remote-workers" -WebSession $session -TimeoutSec 45
$jobs = Invoke-RestMethod "$base/api/admin/jobs?limit=100" -WebSession $session -TimeoutSec 45
$result = [pscustomobject]@{
    environment='AZURE STAGING'
    observedAt=(Get-Date).ToUniversalTime().ToString('o')
    ready=$ready
    eventMode=$event.mode
    publicGatesClosed=(-not ($event.registrationsEnabled -or $event.uploadsEnabled -or
        $event.sandboxEnabled -or $event.officialEnabled -or $event.tournamentEnabled))
    competitionPhase=$competition.phase
    frozenReferences=@($competition.referencePool).Count
    qualificationSeeds=@($competition.evaluationConfig.seeds).Count
    workerRegistrationEnabled=$workers.registrationEnabled
    workerCount=@($workers.workers).Count
    workerState=@($workers.workers | Select-Object name,status,activeJobs,availableSlots,jobsCompleted,jobsFailed)
    queues=$metrics.queues
    dependencyLatencyMs=$metrics.dependencyLatencyMs
    officialGamesRecorded=$metrics.officialGamesRecorded
    officialGamesPerMinute10m=$metrics.officialGamesPerMinute10m
    recentJobs=@($jobs.jobs | Select-Object id,type,status,worker,progressCurrent,progressTotal,attempts,retryCount,errorKind)
}
if ($ready.status -ne 'ready' -or -not $result.publicGatesClosed) { throw 'Staging readiness or access gate verification failed.' }
$result | ConvertTo-Json -Depth 8
