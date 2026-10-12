# One-time permitted Round 1 launch after full Wave 1 checks but incomplete Wave 2.
# Preserves the 50 saved QA identities; never uploads bots, resets data or creates references.
param([string]$Api='https://neural-coliseum-api.onrender.com')
$ErrorActionPreference='Stop'
$kit=Join-Path $PSScriptRoot 'FarmCraft_50_Full_Rehearsal'
$script=Join-Path $kit 'round1_fast_precheck.py'
$driver=Join-Path $kit 'rehearsal.py'
$runner=Join-Path $kit 'Run-Rehearsal.ps1'
$sessionHelper=Join-Path $kit 'restore_missing_qa_sessions.py'
foreach ($file in @($script,$driver,$runner,$sessionHelper)) {if (!(Test-Path -LiteralPath $file)) {throw "Missing $file; extract the Round 1 patch at project root without clearing runtime."}}
if ($Api -cne 'https://neural-coliseum-api.onrender.com') {throw 'Unexpected target. Refusing to submit official jobs.'}
Push-Location $kit
try {
  Write-Host "`n>> Read-only Round 1 eligibility & 49-job drain check" -ForegroundColor Cyan
  & py -3 $script '--base-url' $Api '--wait-minutes' '90'
  if ($LASTEXITCODE -ne 0) {throw 'Official launch blocked by read-only eligibility checks. No official attempts sent.'}
  Write-Host "`n>> Verify and, ONLY IF NECESSARY, explicitly recover QA participant sessions" -ForegroundColor Cyan
  & py -3 $sessionHelper '--base-url' $Api
  if ($LASTEXITCODE -ne 0) {throw 'QA sessions not ready; no official attempts sent.'}
  Write-Host "`nWave-2 sandbox+analytics checks are being skipped ONLY for this authorized QA rehearsal." -ForegroundColor Yellow
  Write-Host "This sends up to 50 real one-attempt official jobs against the 5 selected organizer reference bots. Personal team temp is NEVER submitted." -ForegroundColor Yellow
  $agree=Read-Host 'To submit 50 QA Round 1 official entries, type SUBMIT ROUND1 SKIP WAVE2'
  if ($agree -cne 'SUBMIT ROUND1 SKIP WAVE2') {throw 'Cancelled: no official jobs submitted.'}
  Write-Host "`n>> Official Round 1 submissions" -ForegroundColor Cyan
  & py -3 $driver 'official' '--base-url' $Api '--execute' '--approve-live' '--allow-unverified-wave2'
  if ($LASTEXITCODE -ne 0) {throw 'Official submission routine stopped. Reconcile uncertain official responses before rerunning.'}
  # Stop on unconfirmed/ambiguous official submissions; never send another attempt.
  $st=Get-Content -LiteralPath (Join-Path $kit 'runtime\state.json') -Raw | ConvertFrom-Json
  $bad=@($st.teams.PSObject.Properties | Where-Object { -not $_.Value.official.id -or $_.Value.official.status -eq 'ambiguous' })
  if ($bad.Count -ne 0) {
    Write-Host ('Teams requiring official job ID reconciliation: '+(($bad | ForEach-Object {$_.Name}) -join ', ')) -ForegroundColor Red
    throw 'Some official POSTs may have been accepted despite API error. DO NOT rerun or manually resubmit before reconciliation.'
  }
  Write-Host "SUCCESS: All 50 QA official Round 1 job IDs are confirmed. temp and references untouched." -ForegroundColor Green
  $choice=Read-Host 'Monitor official jobs now? Type MONITOR ROUND1, or press Enter to exit'
  if ($choice -ceq 'MONITOR ROUND1') {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner -Step waitofficial -Api $Api -RepoRoot $PSScriptRoot
    if ($LASTEXITCODE -ne 0) {throw 'Official monitoring stopped. Jobs remain queued/running; do not resubmit.'}
  }
} finally {Pop-Location}
