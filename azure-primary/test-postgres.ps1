$ErrorActionPreference = 'Stop'
$credentialPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-profiles/pgtest-admin.dpapi'
if (-not (Test-Path -LiteralPath $credentialPath)) { throw 'The isolated test credential file is missing.' }
$securePassword = Get-Content -LiteralPath $credentialPath | ConvertTo-SecureString
$env:FARMCRAFT_PG_TEST_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
try {
    Push-Location (Split-Path $PSScriptRoot -Parent)
    try { & python azure-primary/test_postgres.py; if ($LASTEXITCODE -ne 0) { throw 'Database smoke test failed.' } }
    finally { Pop-Location }
} finally {
    Remove-Item Env:FARMCRAFT_PG_TEST_PASSWORD -ErrorAction SilentlyContinue
}
