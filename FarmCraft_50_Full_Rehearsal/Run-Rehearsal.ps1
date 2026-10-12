param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('validate','benchmark','preflight','cleanup-plan','cleanup-execute','provision','sandbox1','wait1','analytics1','browser1','sandbox2','wait2','analytics2','browser2','heartbeat','snapshot','official','waitofficial','tournament','report','reconcile')]
  [string]$Step,
  [string]$Api = 'https://neural-coliseum-api.onrender.com',
  [string]$Frontend = 'https://neural-coliseum.onrender.com',
  [string]$RepoRoot = 'D:\kaggriculture\Kaggriculture',
  [string]$GamePython = 'python',
  [string]$PlanSha = '',
  [string]$BackupFile = '',
  [int]$DurationMinutes = 30,
  [switch]$ApproveLive,
  [switch]$PermitUnbenchmarked
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$common = @('--base-url', $Api)
$mutating = $Step -in @('provision','sandbox1','sandbox2','heartbeat','official')
if ($mutating) {
  if (-not $ApproveLive -and $Api -like '*onrender.com*') {
    throw 'This phase modifies LIVE data. Requires -ApproveLive after verifying the rehearsal window.'
  }
  $common += @('--execute')
  if ($ApproveLive) {$common += '--approve-live'}
}
if ($PermitUnbenchmarked) {$common += '--permit-unbenchmarked'}
function Call-Py ([string]$Script, [string[]]$Arguments) {
  & py -3 ".\$Script" @Arguments
  if ($LASTEXITCODE -ne 0) { throw "Command failed: $Script (exit $LASTEXITCODE). Check reports and runtime/state.json; do not blindly rerun POST requests." }
}
switch ($Step) {
  'validate' { Call-Py 'validate_agents.py' @() }
  'benchmark' { Call-Py 'benchmark_bots.py' @('--repo-root',$RepoRoot,'--python',$GamePython) }
  'preflight' { Call-Py 'rehearsal.py' (@('preflight')+$common) }
  'cleanup-plan' { Call-Py 'cleanup_old_qa.py' @('--repo-root',$RepoRoot) }
  'cleanup-execute' {
    if (-not $PlanSha -or -not $BackupFile) { throw 'Supply exact -PlanSha and -BackupFile from the approved cleanup plan and verified backup.' }
    $typed = Read-Host 'This deletes ONLY previous QA26_B2C9C5_01..20 from selected PostgreSQL. Type DELETE OLD QA20 ONLY'
    if ($typed -cne 'DELETE OLD QA20 ONLY') { throw 'Cleanup not approved' }
    Call-Py 'cleanup_old_qa.py' @('--repo-root',$RepoRoot,'--execute','--plan-sha',$PlanSha,'--backup-file',$BackupFile,'--confirm',$typed)
  }
  'provision' { Call-Py 'rehearsal.py' (@('provision')+$common) }
  'sandbox1' { Call-Py 'rehearsal.py' (@('sandbox','--wave','1')+$common) }
  'wait1' { Call-Py 'rehearsal.py' (@('monitor','--phase','sandbox1','--max-minutes','180')+$common) }
  'analytics1' { Call-Py 'rehearsal.py' (@('analytics','--wave','1')+$common) }
  'browser1' { Call-Py 'ui_browser_check.py' @('--frontend',$Frontend,'--api',$Api,'--wave','1') }
  'sandbox2' { Call-Py 'rehearsal.py' (@('sandbox','--wave','2')+$common) }
  'wait2' { Call-Py 'rehearsal.py' (@('monitor','--phase','sandbox2','--max-minutes','180')+$common) }
  'analytics2' { Call-Py 'rehearsal.py' (@('analytics','--wave','2')+$common) }
  'browser2' { Call-Py 'ui_browser_check.py' @('--frontend',$Frontend,'--api',$Api,'--wave','2') }
  'heartbeat' { Call-Py 'rehearsal.py' (@('heartbeat','--duration-minutes',[string]$DurationMinutes)+$common) }
  'snapshot' { Call-Py 'rehearsal.py' (@('snapshot')+$common) }
  'official' { Call-Py 'rehearsal.py' (@('official')+$common) }
  'waitofficial' { Call-Py 'rehearsal.py' (@('monitor','--phase','round1','--max-minutes','360')+$common) }
  'tournament' { Call-Py 'rehearsal.py' (@('tournament','--max-minutes','360')+$common) }
  'report' { Call-Py 'rehearsal.py' (@('report')+$common) }
  'reconcile' { Call-Py 'rehearsal.py' (@('reconcile')+$common) }
}
