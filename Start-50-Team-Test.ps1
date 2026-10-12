# FarmCraft 50-Team organizer testing — main-project entry point.
# Set-ExecutionPolicy is not changed persistently.
param(
  [ValidateSet('Menu','Check','ResetOldTests','Sandboxes','RecoverSandbox','RepairTwo','Round1','Round1Fast','Round2','Report')]
  [string]$Mode = 'Menu',
  [string]$Api = 'https://neural-coliseum-api.onrender.com'
)
$ErrorActionPreference = 'Stop'
$kit = Join-Path $PSScriptRoot 'FarmCraft_50_Full_Rehearsal'
$runner = Join-Path $kit 'Run-Rehearsal.ps1'
$reset = Join-Path $kit 'reset_old_round_and_qa.py'
if (-not (Test-Path -LiteralPath $runner)) { throw "Missing original rehearsal kit in $kit. Keep the 50 bots and your existing runtime state." }

function Invoke-Python([string]$script, [string[]]$arguments) {
  & py -3 $script @arguments
  if ($LASTEXITCODE -ne 0) { throw "Stopped: $script failed. See error above. No blind retries." }
}
function Step([string]$name, [bool]$live=$false) {
  $argv=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$runner,'-Step',$name,'-Api',$Api,'-RepoRoot',$PSScriptRoot)
  if ($live) {$argv += '-ApproveLive'}
  Write-Host "`n>> $name" -ForegroundColor Cyan
  & powershell.exe @argv
  if ($LASTEXITCODE -ne 0) { throw "Stopped at $name. Never blindly retry POST requests." }
}
function Preflight {
  Step 'preflight'
  $file=Join-Path $kit 'runtime\preflight.json'
  $snap=Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
  if (!$snap.protectedTeamExists -or @($snap.protectedTeam).Count -ne 1 -or $snap.selectedReferenceCount -ne 5) {
    throw 'Protection checks failed for temp or the five selected Round 1 reference bots.'
  }
  Write-Host "Protected: temp and five selected references; current phase $($snap.competitionPhase)." -ForegroundColor Green
  return $snap
}
function PostgreSQLTool([string]$tool) {
  $existing=Get-Command $tool -ErrorAction SilentlyContinue
  if ($existing) { return $existing.Source }
  $parent=${env:ProgramFiles}
  if ($parent) {
    $paths=Get-ChildItem -Path (Join-Path $parent 'PostgreSQL\*\bin') -Filter "$tool.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending
    if ($paths) { return @($paths)[0].FullName }
  }
  $custom=Read-Host "Path to $tool.exe (PostgreSQL client tools required)"
  if (-not (Test-Path -LiteralPath $custom -PathType Leaf)) {
    throw "Cannot find $tool. Install PostgreSQL client tools (pg_dump and pg_restore) then retry. No changes made."
  }
  return $custom
}
function With-Database([scriptblock]$action) {
  # Always prompt once, in this process only. Never show or store connection URL.
  if ($env:DATABASE_URL) { throw 'Existing DATABASE_URL environment variable detected. Clear it first, then allow secure prompting to avoid wrong-database access.' }
  $secret=Read-Host 'Paste Neon production PostgreSQL DATABASE_URL (hidden)' -AsSecureString
  $url=[System.Net.NetworkCredential]::new('',$secret).Password
  Remove-Variable secret -ErrorAction SilentlyContinue
  if ([string]::IsNullOrWhiteSpace($url) -or $url -notmatch '^postgres(ql)?(\+psycopg)?://') {
    throw 'Neon URL was empty or invalid. No changes made.'
  }
  $env:DATABASE_URL=$url
  Remove-Variable url -ErrorAction SilentlyContinue
  try { & $action } finally { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
}
function ResetOldTests {
  if (-not (Test-Path -LiteralPath $reset)) {throw "Reset script missing at $reset. Extract the update ZIP to the repository root first."}
  $p=Preflight
  if ($p.competitionPhase -notin @('QUALIFICATION_OPEN','SETUP')) {
    throw "Phase $($p.competitionPhase) is not eligible for this reset. No changes made."
  }
  Write-Host "This is a verified OLD TEST ROUND reset, not a wipe of all $($p.registeredTeams) teams." -ForegroundColor Yellow
  Write-Host 'Deletion scope: QA26_B2C9C5_01 through _20 ONLY. temp and five references are protected.' -ForegroundColor Yellow
  $confirmation=Read-Host 'Type YES OLD ROUND IS TEST ONLY to continue with plan + full backup'
  if ($confirmation -cne 'YES OLD ROUND IS TEST ONLY') { throw 'Reset cancelled.' }
  With-Database {
    # A verified database dump is essential before direct edits to Neon.
    $dump=PostgreSQLTool 'pg_dump'
    $restore=PostgreSQLTool 'pg_restore'
    $working=Join-Path $kit 'runtime'
    if (-not (Test-Path $working)) { New-Item $working -ItemType Directory -Force | Out-Null }
    Invoke-Python $reset @()
    $plan=Get-Content -LiteralPath (Join-Path $working 'reset_qa_plan.json') -Raw | ConvertFrom-Json
    if ($plan.preview.target.database -eq $null -or $plan.preview.target.host -eq $null) {throw 'Database target unknown; refuse.'}
    Write-Host "`nBACKUP WILL BE TAKEN FROM $($plan.preview.target.host) / $($plan.preview.target.database)" -ForegroundColor Yellow
    Write-Host 'Preserving temp, all its submissions, five reference bots and every non-QA20 team.' -ForegroundColor Green
    $backup=Join-Path $working ("farmcraft-pre-reset-{0}.dump" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $pgUrl=($env:DATABASE_URL -replace '^postgresql\+psycopg:', 'postgresql:')
    & $dump "--dbname=$pgUrl" '--format=custom' '--no-owner' '--no-acl' "--file=$backup"
    Remove-Variable pgUrl -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) {throw 'pg_dump failed; database unchanged'}
    if (-not (Test-Path -LiteralPath $backup) -or (Get-Item $backup).Length -lt 10000) {
      throw 'Backup missing or too small; database unchanged'
    }
    $inventory=& $restore '--list' $backup
    if ($LASTEXITCODE -ne 0) {throw 'pg_restore --list could not read backup; database unchanged'}
    foreach ($required in @('reference_bots','teams','submissions','competition_state','event_config')) {
      if (-not (($inventory -join "`n") -match [regex]::Escape($required))) {
        throw "Backup inventory missing $required; database unchanged"
      }
    }
    $sha=(Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant()
    $verify=@{sha256=$sha;sourceHost=$plan.preview.target.host;sourceDatabase=$plan.preview.target.database;backupPath=$backup}
    [System.IO.File]::WriteAllText((Join-Path $working 'backup_verified.json'), ($verify | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "`nBackup created and catalog verified: $backup" -ForegroundColor Green
    Write-Host "Plan SHA256: $($plan.planSha256)" -ForegroundColor Cyan
    $typed=Read-Host 'LAST CONFIRMATION: type RESET OLD QA ROUND ONLY to remove exactly those QA accounts and reset old qualification'
    if ($typed -cne 'RESET OLD QA ROUND ONLY') {throw 'No deletion; backup retained safely.'}
    Invoke-Python $reset @('--execute','--approve-hash',$plan.planSha256,'--backup-file',$backup,'--confirmation',$typed)
  }
  Write-Host "`nReset complete. Confirming via LIVE admin API..." -ForegroundColor Cyan
  $updated=Preflight
  if ($updated.competitionPhase -ne 'SETUP') {throw 'Admin did not show SETUP; stop here.'}
  Write-Host 'Safe to proceed with 50-team sandbox rehearsal after reviewing admin page.' -ForegroundColor Green
}
function RunSandboxes {
  $p=Preflight
  if ($p.competitionPhase -ne 'SETUP') { throw 'Expected SETUP; run old-round reset first.' }
  $ok=Read-Host 'Run 50 registration/upload workflows and 100 REAL sandbox games? Type RUN 50 SANDBOXES'
  if ($ok -cne 'RUN 50 SANDBOXES') {throw 'Cancelled'}
  Step 'validate'; Step 'provision' $true
  Step 'sandbox1' $true; Step 'wait1'; Step 'analytics1'
  Step 'sandbox2' $true; Step 'wait2'; Step 'analytics2'
  Step 'snapshot'; Step 'report'
  Write-Host '100 sandbox jobs checkpoint reached. Start Round 1 yourself in Admin.' -ForegroundColor Green
}
function ResumeSandboxes {
  $resume=Join-Path $PSScriptRoot 'Resume-FarmCraft-Sandboxes.ps1'
  if (!(Test-Path -LiteralPath $resume)) {throw 'Missing Resume-FarmCraft-Sandboxes.ps1. Extract the sandbox recovery ZIP to repository root.'}
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $resume -Api $Api
  if ($LASTEXITCODE -ne 0) { throw 'Sandbox recovery stopped. Check output. No blind POST retries.' }
}
function RepairTwo {
  $script=Join-Path $kit 'repair_missing_003_004.py'
  if (-not (Test-Path -LiteralPath $script)) {throw 'Missing repair_missing_003_004.py; extract the 003/004 fix ZIP into the main FarmCraft folder.'}
  Write-Host 'Checking 003 and 004 read-only first. No registration/upload/delete. A new job is sent only after an explicit confirmation.' -ForegroundColor Yellow
  Push-Location $kit
  try { & py -3 $script '--base-url' $Api }
  finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) {throw '003/004 repair stopped. No blind POST retries; inspect lines above.'}
  Write-Host 'Repair/reconciliation finished. Choose 7 (Resume sandboxes) to monitor completed jobs and proceed.' -ForegroundColor Green
}
function RunRound1 {
  $p=Preflight
  if ($p.competitionPhase -ne 'QUALIFICATION_OPEN') {throw 'Open Round 1 yourself in Admin before sending official submissions.'}
  $ok=Read-Host 'Submit official jobs for the 50 QA teams (NEVER temp)? Type SUBMIT QA50'
  if ($ok -cne 'SUBMIT QA50') {throw 'Cancelled'}
  Step 'official' $true; Step 'waitofficial'; Step 'snapshot'; Step 'report'
}
function RunRound1Fast {
  $file=Join-Path $PSScriptRoot 'Quick-Round1.ps1'
  if (!(Test-Path $file)) {throw 'Missing Quick-Round1.ps1; extract Round 1 patch ZIP into repository root.'}
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $file -Api $Api
  if ($LASTEXITCODE -ne 0) {throw 'Fast Round 1 launch stopped. Do not send duplicate official submissions.'}
}
function RunRound2 {
  Preflight | Out-Null
  Step 'tournament'; Step 'snapshot'; Step 'report'
}
function RunAction([string]$action) {
  switch ($action) {
    'Check'         { Preflight | Out-Null }
    'ResetOldTests' { ResetOldTests }
    'Sandboxes'     { RunSandboxes }
    'RecoverSandbox'{ ResumeSandboxes }
    'RepairTwo'     { RepairTwo }
    'Round1'        { RunRound1 }
    'Round1Fast'    { RunRound1Fast }
    'Round2'        { RunRound2 }
    'Report'        { Step 'snapshot'; Step 'report' }
    default { throw "Unknown action $action" }
  }
}
if ($Mode -ne 'Menu') { RunAction $Mode; exit }
while ($true) {
  Write-Host "`nFARMCRAFT | 1 Check  2 Reset old test round + QA20  3 Run 100 sandboxes  4 Round 1  5 Round 2  6 Report  7 Resume sandboxes  8 Repair missing 003/004  9 Round 1 skip wave2  0 Exit" -ForegroundColor Cyan
  $pick=Read-Host 'Choose'
  if ($pick -eq '0') {break}
  $choices=@{'1'='Check';'2'='ResetOldTests';'3'='Sandboxes';'4'='Round1';'5'='Round2';'6'='Report';'7'='RecoverSandbox';'8'='RepairTwo';'9'='Round1Fast'}
  if (!$choices.ContainsKey($pick)) {continue}
  try {RunAction $choices[$pick]} catch {Write-Host "STOP: $($_.Exception.Message)" -ForegroundColor Red}
}
