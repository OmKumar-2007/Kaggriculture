# Copies the Phase 4 staging Admin password to this Windows user's clipboard.
# Run interactively on the same Windows account that created the DPAPI file.
$ErrorActionPreference = 'Stop'
$credentialPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-profiles/phase4-admin.dpapi'
if (-not (Test-Path -LiteralPath $credentialPath)) {
    throw 'The local staging Admin password archive is unavailable.'
}
$secure = Get-Content -LiteralPath $credentialPath | ConvertTo-SecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $password = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    Set-Clipboard -Value $password
} finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $password = $null
    $secure.Dispose()
}
Write-Host 'Staging Admin password copied locally. Paste it into the staging Admin login, then clear your clipboard.'
