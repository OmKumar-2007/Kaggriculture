param([ValidateRange(120,900)][int]$TimeoutSeconds = 450)

# Controlled staging-only runner. The operator must disable the temporary
# fixture flag and drain/revoke the temporary worker in a finally procedure.

$ErrorActionPreference = 'Stop'
$base = 'https://farmcraft-staging-api.livelybush-912ee7d2.koreacentral.azurecontainerapps.io'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$script:csrf = $null

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
        $event.tournamentEnabled) { throw 'Public participant gates are not closed.' }
}

if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required for protected multipart upload.' }
$app = & az containerapp show -g rg-farmcraft-azure-staging-20261012 -n farmcraft-staging-api -o json | ConvertFrom-Json
$flag = $app.properties.template.containers[0].env | Where-Object name -eq 'FARMCRAFT_STAGING_FIXTURE_ENABLED' | Select-Object -ExpandProperty value
if ($flag -ne '1' -or $app.properties.latestReadyRevisionName -ne $app.properties.latestRevisionName) {
    throw 'The temporary staging fixture flag is not active on a ready revision.'
}
$secure = Get-Content -LiteralPath (Join-Path $root 'config/local-profiles/phase4-admin.dpapi') | ConvertTo-SecureString
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
Assert-Closed (Admin GET '/event')
$competition = Admin GET '/competition'
if ($competition.phase -ne 'QUALIFICATION_OPEN' -or $competition.referencePool.Count -ne 3 -or
    $competition.evaluationConfig.seeds.Count -ne 1 -or $competition.evaluationConfig.sides.Count -ne 2) {
    throw 'Frozen six-game qualification snapshot is not available.'
}
$worker = (Admin GET '/remote-workers').workers | Where-Object name -eq 'farmcraft-staging-03' | Select-Object -First 1
if ($worker.status -ne 'idle' -or $worker.availableSlots -ne 1) { throw 'Staging worker 03 is not ready.' }
$source = Join-Path $root 'contestant_starter/agent.py'
$upload = Invoke-RestMethod -Method Post -Uri "$base/api/admin/staging-fixtures/upload" -WebSession $session `
    -Headers @{'x-admin-csrf'=$script:csrf} -Form @{
        file=Get-Item -LiteralPath $source
        confirmation='CREATE ISOLATED STAGING FIXTURE'
    } -TimeoutSec 90
Write-Host "Created rehearsal-only staging team $($upload.team)."
$queued = Admin POST "/staging-fixtures/$($upload.team)/queue-official" @{confirmation='QUEUE SIX STAGING GAMES'}
Write-Host "Queued official staging job $($queued.jobId)."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Seconds 5
    $job = Admin GET "/jobs/$($queued.jobId)"
} while ($job.status -notin @('completed','failed','timeout','cancelled') -and (Get-Date) -lt $deadline)
if ($job.status -ne 'completed') { throw "Official staging job $($queued.jobId) ended $($job.status)." }
$games = @($job.result.matchResults)
if ($job.result.games -ne 6 -or $games.Count -ne 6 -or
    @($games | ForEach-Object replayId | Sort-Object -Unique).Count -ne 6) {
    throw 'Official staging result does not contain six distinct replay-backed games.'
}
$replayStatus = @()
foreach ($game in $games) {
    $response = Invoke-WebRequest "$base/replays/$($game.replayId)/playback" -WebSession $session -TimeoutSec 45
    $replayStatus += [int]$response.StatusCode
}
if (@($replayStatus | Where-Object { $_ -ne 200 }).Count) { throw 'A staging replay could not be read.' }
Assert-Closed (Admin GET '/event')
[pscustomobject]@{team=$upload.team;jobId=$queued.jobId;games=6;
    rating=$job.result.rating;worker=$job.worker;replayReads=6;
    publicGates='closed'} | ConvertTo-Json -Depth 3
