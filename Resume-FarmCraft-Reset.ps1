# Resume the approved old QA round reset using the *existing*, checksum-verified pg_dump.
# The previous attempt stopped while parsing UTF8 BOM in backup_verified.json, prior to any SQL deletion.
param()
$ErrorActionPreference = 'Stop'
$kit = Join-Path $PSScriptRoot 'FarmCraft_50_Full_Rehearsal'
$runtime = Join-Path $kit 'runtime'
$reset = Join-Path $kit 'reset_old_round_and_qa.py'
$planFile = Join-Path $runtime 'reset_qa_plan.json'
$markerFile = Join-Path $runtime 'backup_verified.json'
if (-not (Test-Path -LiteralPath $reset -PathType Leaf)) { throw "Reset script missing: $reset" }
if (-not (Test-Path -LiteralPath $planFile -PathType Leaf)) { throw "Existing reset plan missing: $planFile. Nothing changed." }
if (-not (Test-Path -LiteralPath $markerFile -PathType Leaf)) { throw "Existing verified-backup marker missing: $markerFile. Nothing changed." }
$plan = Get-Content -LiteralPath $planFile -Raw -Encoding UTF8 | ConvertFrom-Json
$marker = Get-Content -LiteralPath $markerFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($plan.preview.target.host -ne $marker.sourceHost -or $plan.preview.target.database -ne $marker.sourceDatabase) {
    throw 'Backup marker and saved deletion plan point at different databases; no changes made.'
}
$allowed = @(1..20 | ForEach-Object { 'QA26_B2C9C5_{0:D2}' -f $_ })
$targetNames = @($plan.preview.oldQATeams | ForEach-Object { $_.username })
foreach ($target in $targetNames) {
    if ($allowed -cnotcontains $target) { throw "Unexpected deletion target $target. Refuse to run." }
}
if ($targetNames.Count -ne (@($targetNames | Select-Object -Unique)).Count) { throw 'Duplicate QA deletion targets; refuse to run.' }
if ($plan.preview.protectedTeam.username -cne 'temp' -or @($plan.preview.referenceBots | Where-Object { $_.selected -and $_.enabled -and -not $_.archived }).Count -ne 5) {
    throw 'Protected temp or selected references not verified by the saved plan; refuse.'
}
if ($plan.preview.competition.phase -notin @('SETUP','QUALIFICATION_OPEN')) { throw 'Unexpected plan phase; refuse.' }
$backup = [string]$marker.backupPath
if (-not (Test-Path -LiteralPath $backup -PathType Leaf) -or (Get-Item -LiteralPath $backup).Length -lt 10000) {
    throw 'Original PostgreSQL backup missing or unexpectedly small; no changes made.'
}
$backupHash = (Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant()
if ($backupHash -ne $marker.sha256) { throw 'Backup SHA256 mismatch; no changes made.' }
$restore = Get-Command pg_restore -ErrorAction SilentlyContinue
if ($restore) { $restorePath = $restore.Source }
else {
    $pgFolder = Join-Path $env:ProgramFiles 'PostgreSQL\18\bin\pg_restore.exe'
    if (-not (Test-Path -LiteralPath $pgFolder -PathType Leaf)) { throw "PostgreSQL pg_restore.exe not found at $pgFolder; no changes made." }
    $restorePath = $pgFolder
}
$inventory = & $restorePath '--list' $backup
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL cannot list the backup; no changes made.' }
foreach ($required in @('teams','submissions','reference_bots','competition_state','event_config')) {
    if (-not (($inventory -join "`n") -match [regex]::Escape($required))) { throw "Backup missing expected table $required; no changes made." }
}
Write-Host "`nExisting backup: $backup" -ForegroundColor Green
Write-Host "Backup SHA256 verified; database: $($marker.sourceHost) / $($marker.sourceDatabase)" -ForegroundColor Green
Write-Host "Exact saved plan hash: $($plan.planSha256)" -ForegroundColor Cyan
Write-Host "Targeted QA teams: $($targetNames.Count); temp + five references protected; unrelated teams preserved." -ForegroundColor Yellow
Write-Host 'The reset Python code will recompute the FULL live database snapshot, verify identical plan SHA, refuse active jobs, and roll back on any invariant failure.' -ForegroundColor Yellow
$confirm = Read-Host 'To resume the approved reset, type RESET OLD QA ROUND ONLY'
if ($confirm -cne 'RESET OLD QA ROUND ONLY') { throw 'Cancelled; no database changes.' }
if ($env:DATABASE_URL) { throw 'DATABASE_URL already set in this PowerShell process; unset it to avoid targeting the wrong database.' }
$secret = Read-Host 'Paste Neon production PostgreSQL DATABASE_URL (hidden)' -AsSecureString
$url = [System.Net.NetworkCredential]::new('', $secret).Password
Remove-Variable secret -ErrorAction SilentlyContinue
if ([string]::IsNullOrWhiteSpace($url) -or $url -notmatch '^postgres(ql)?(\+psycopg)?://') { throw 'Invalid/empty PostgreSQL URL; no changes.' }
try {
    $env:DATABASE_URL = $url
    & py -3 $reset '--execute' '--approve-hash' ([string]$plan.planSha256) '--backup-file' $backup '--confirmation' $confirm
    if ($LASTEXITCODE -ne 0) { throw 'Reset halted safely. Do not blindly repeat. Share the STOP line, but never share DATABASE_URL.' }
} finally {
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Variable url -ErrorAction SilentlyContinue
}
Write-Host "`nRESET SUCCESS. Start your original main launcher and choose 1 (Check); the phase should be SETUP." -ForegroundColor Green
