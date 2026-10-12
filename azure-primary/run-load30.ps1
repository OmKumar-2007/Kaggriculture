param(
    [Parameter(Mandatory=$true)][ValidateSet('preflight','start','monitor','audit','round2','audit2')][string]$Action,
    [int]$MaxMinutes = 120
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$protected = Join-Path $root 'config/local-profiles/phase4-admin.dpapi'
$secure = Get-Content -LiteralPath $protected | ConvertTo-SecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:FARMCRAFT_STAGING_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    & python (Join-Path $PSScriptRoot 'run-load30.py') $Action --max-minutes $MaxMinutes
    if ($LASTEXITCODE -ne 0) { throw "Load30 $Action failed with exit code $LASTEXITCODE" }
} finally {
    Remove-Item Env:FARMCRAFT_STAGING_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secure.Dispose()
}
