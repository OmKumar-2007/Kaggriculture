param([ValidateSet('preflight','close-gates','smoke','metrics','round2-metrics','execute','audit','drain-workers','resume-workers')][string]$Action='preflight', [string]$JobId='')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$protected = Join-Path $repo 'config/local-profiles/phase4-admin.dpapi'
$secure = Get-Content -LiteralPath $protected | ConvertTo-SecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:FARMCRAFT_STAGING_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ($Action -eq 'preflight') {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'preflight_50.py')
    } elseif ($Action -eq 'close-gates') {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'close_staging_gates.py')
    } elseif ($Action -eq 'smoke') {
        $smokeArgs = @((Join-Path $PSScriptRoot 'smoke_worker.py'))
        if ($JobId) { $smokeArgs += @('--job-id', $JobId) }
        & (Join-Path $repo '.venv/Scripts/python.exe') @smokeArgs
    } elseif ($Action -eq 'metrics') {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'collect_50_metrics.py')
    } elseif ($Action -eq 'round2-metrics') {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'collect_round2_metrics.py')
    } elseif ($Action -eq 'audit') {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'audit_50.py')
    } elseif ($Action -eq 'drain-workers') {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'set_worker_modes.py') drain
    } elseif ($Action -eq 'resume-workers') {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'set_worker_modes.py') resume
    } else {
        & (Join-Path $repo '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'run_50_live.py') --execute --round2 --hold-before-burst
    }
    if ($LASTEXITCODE -ne 0) { throw "FarmCraft 50 action failed with exit code $LASTEXITCODE" }
} finally {
    Remove-Item Env:FARMCRAFT_STAGING_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secure.Dispose()
}
