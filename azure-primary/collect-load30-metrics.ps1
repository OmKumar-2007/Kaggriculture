$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$secure = Get-Content -LiteralPath (Join-Path $root 'config/local-profiles/phase4-admin.dpapi') | ConvertTo-SecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:FARMCRAFT_STAGING_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    & python (Join-Path $PSScriptRoot 'collect-load30-metrics.py')
} finally {
    Remove-Item Env:FARMCRAFT_STAGING_ADMIN_PASSWORD -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $secure.Dispose()
}
