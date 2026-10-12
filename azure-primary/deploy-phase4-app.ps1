param([switch]$Approved)

$ErrorActionPreference = 'Stop'
if (-not $Approved) { throw 'Separate Phase 4 staging app approval is required.' }
$subscription = (& az account show --query id --output tsv).Trim()
if ($LASTEXITCODE -ne 0 -or $subscription -ne 'edcb16c2-9bcf-4533-8ca0-d182aaac9b70') {
    throw 'Active Azure subscription is not the reviewed Azure for Students subscription.'
}
$group = 'rg-farmcraft-azure-staging-20261012'
$appName = 'farmcraft-staging-api'
$registry = 'fcstg6chsyox4t2zfa'
$digest = 'sha256:84ae81bbdefb32f4a4e4789aca65b215e401f5f8ee4f1a79601dee07f4d8ee06'
if ((& az group exists --name $group).Trim() -ne 'true') { throw 'Approved staging resource group is absent.' }
$apps = & az containerapp list --resource-group $group --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or @($apps | Where-Object name -eq $appName).Count -ne 0) {
    throw 'Staging app already exists or app inventory failed; inspect it before retrying.'
}
$manifest = & az acr manifest show-metadata --registry $registry --name 'farmcraft:phase4-20261012' --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $manifest.digest -ne $digest) {
    throw 'Pinned image digest is absent or changed.'
}

$credentialDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-profiles'
$pgCredentialPath = Join-Path $credentialDirectory 'phase4-pg-admin.dpapi'
$adminCredentialPath = Join-Path $credentialDirectory 'phase4-admin.dpapi'
$sessionCredentialPath = Join-Path $credentialDirectory 'phase4-session.dpapi'
if (-not (Test-Path -LiteralPath $pgCredentialPath)) { throw 'Staging PostgreSQL credential archive is absent.' }
if ((Test-Path -LiteralPath $adminCredentialPath) -or (Test-Path -LiteralPath $sessionCredentialPath)) {
    throw 'Staging app credentials already exist; inspect before redeploying.'
}

function New-RandomBytes([int]$length) {
    $bytes = New-Object byte[] $length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ,$bytes
}

$pgSecure = Get-Content -LiteralPath $pgCredentialPath | ConvertTo-SecureString
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($pgSecure)
try { $pgPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
finally { [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
$adminPassword = [Convert]::ToBase64String((New-RandomBytes 36)) + 'aA1!'
$sessionSecret = [Convert]::ToBase64String((New-RandomBytes 48))
$salt = -join ((New-RandomBytes 18) | ForEach-Object { $_.ToString('x2') })
$kdf = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
    [System.Text.Encoding]::UTF8.GetBytes($adminPassword),
    [System.Text.Encoding]::UTF8.GetBytes($salt),
    310000,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256)
try { $hash = [BitConverter]::ToString($kdf.GetBytes(32)).Replace('-', '').ToLowerInvariant() }
finally { $kdf.Dispose() }
$adminHash = "pbkdf2_sha256`$310000`$$salt`$$hash"
$encodedPgPassword = [uri]::EscapeDataString($pgPassword)
$databaseUrl = "postgresql+psycopg://farmcraft_admin:$encodedPgPassword@farmcraftstgpg20261012omk.postgres.database.azure.com/farmcraft?sslmode=require"

$adminPassword | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $adminCredentialPath
$sessionSecret | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $sessionCredentialPath

$parameters = @{ parameters = @{
    appName = @{ value = $appName }
    environmentName = @{ value = 'fcstg-environment' }
    registryName = @{ value = $registry }
    pullIdentityName = @{ value = 'fcstg-pull' }
    storageAccountName = @{ value = $registry }
    image = @{ value = "$registry.azurecr.io/farmcraft@$digest" }
    databaseUrl = @{ value = $databaseUrl }
    adminPasswordHash = @{ value = $adminHash }
    adminSessionSecret = @{ value = $sessionSecret }
    minReplicas = @{ value = 0 }
} }
$tempFile = New-TemporaryFile
try {
    $acl = Get-Acl -LiteralPath $tempFile.FullName
    $acl.SetAccessRuleProtection($true, $false)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $tempFile.FullName -AclObject $acl
    $parameters | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tempFile.FullName -Encoding utf8
    $argument = '@' + $tempFile.FullName
    & az deployment group create --name 'farmcraft-phase4-app-20261012' --resource-group $group --template-file (Join-Path $PSScriptRoot 'app.bicep') --parameters $argument --query properties.provisioningState --output tsv
    if ($LASTEXITCODE -ne 0) {
        throw 'Staging app deployment failed. Inspect partial resources; do not auto-clean or change production.'
    }
} finally {
    $pgPassword = $null
    $adminPassword = $null
    $sessionSecret = $null
    $databaseUrl = $null
    Remove-Item -LiteralPath $tempFile.FullName -Force -ErrorAction SilentlyContinue
}
