# Safely recover unknown IDs from organizer job history, then finish sandbox waves.
# Does not alter temp, reference bots, event configuration, or database competition phase.
param([string]$Api='https://neural-coliseum-api.onrender.com')
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$kit=Join-Path $root 'FarmCraft_50_Full_Rehearsal'
$repair=Join-Path $kit 'reconcile_sandbox_jobs.py'
$runner=Join-Path $kit 'Run-Rehearsal.ps1'
if (!(Test-Path $repair) -or !(Test-Path $runner)) {throw 'Install the repair ZIP at FarmCraft project root (without deleting runtime).'}
function Step([string]$name,[bool]$live=$false) {
  Write-Host "`n>> $name" -ForegroundColor Cyan
  $args=@('-NoProfile','-ExecutionPolicy','Bypass','-File',$runner,'-Step',$name,'-Api',$Api,'-RepoRoot',$root)
  if ($live) {$args+='-ApproveLive'}
  & powershell.exe @args
  if ($LASTEXITCODE -ne 0) {throw "Stopped at $name. Check output. No duplicate submission attempts."}
}
function Recover([int]$wave) {
  Write-Host "`n>> Read-only server reconciliation of sandbox wave $wave" -ForegroundColor Cyan
  Push-Location $kit
  try { & py -3 $repair '--wave' ([string]$wave) '--base-url' $Api }
  finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) {throw "Wave $wave has unresolved job IDs. No jobs were resubmitted; do not rerun option 3."}
}
Recover 1
Step 'wait1'
Step 'analytics1'
Write-Host "`nWave 1 monitoring/analytics completed." -ForegroundColor Green
$choice=Read-Host 'To launch the 50 NEW wave-2 sandbox jobs, type START WAVE 2 (or Enter to stop)'
if ($choice -cne 'START WAVE 2') {Write-Host 'Stopped safely after wave 1. No wave-2 jobs launched.';exit 0}
# Renew only genuinely missing/expired EXISTING QA sessions, with an explicit
# organizer confirmation. Never register a new team as a recovery workaround.
Write-Host "`n>> Verify QA participant sessions before wave 2" -ForegroundColor Cyan
Push-Location $kit
try { & py -3 '.\restore_missing_qa_sessions.py' '--base-url' $Api }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0) {throw 'QA session recovery incomplete. Zero wave-2 POST requests sent.'}
# This helper is for the specific checkpoint where wave 2 has NOT yet been attempted.
# Require zero wave-2 state entries to avoid repeat POSTs after interrupted submissions.
$state=Get-Content -LiteralPath (Join-Path $kit 'runtime\state.json') -Raw | ConvertFrom-Json
$existing= @($state.teams.PSObject.Properties | Where-Object { $_.Value.sandbox.'2' })
if ($existing.Count -gt 0) {throw "Wave 2 already has $($existing.Count) saved entries. Refusing automatic POST; use manual recovery instead."}
Step 'sandbox2' $true
Recover 2
Step 'wait2'
Step 'analytics2'
Step 'snapshot'
Step 'report'
Write-Host "`nBoth sandbox waves complete. Inspect reports; then start Round 1 manually from Admin." -ForegroundColor Green
