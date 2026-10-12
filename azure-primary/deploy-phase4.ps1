param([switch]$Approved)

$ErrorActionPreference = 'Stop'
if (-not $Approved) { throw 'Explicit Phase 4 infrastructure approval is required.' }
$expectedSubscription = 'edcb16c2-9bcf-4533-8ca0-d182aaac9b70'
$resourceGroupName = 'rg-farmcraft-azure-staging-20261012'
$serverName = 'farmcraftstgpg20261012omk'
$location = 'koreacentral'
$subscription = (& az account show --query id --output tsv).Trim()
if ($LASTEXITCODE -ne 0 -or $subscription -ne $expectedSubscription) {
    throw 'Active Azure subscription does not match the approved Azure for Students subscription.'
}
$exists = (& az group exists --name $resourceGroupName).Trim()
if ($LASTEXITCODE -ne 0 -or $exists -ne 'false') {
    throw 'Staging group already exists. Inspect it instead of deploying over it.'
}

$credentialDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-profiles'
New-Item -ItemType Directory -Path $credentialDirectory -Force | Out-Null
$credentialPath = Join-Path $credentialDirectory 'phase4-pg-admin.dpapi'
if (Test-Path -LiteralPath $credentialPath) {
    throw 'A staging credential archive already exists; inspect it before proceeding.'
}
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$passwordBytes = New-Object byte[] 36
try { $random.GetBytes($passwordBytes) } finally { $random.Dispose() }
$password = [Convert]::ToBase64String($passwordBytes) + 'aA1!'
$password | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $credentialPath

$parameters = @{ parameters = @{
    resourceGroupName = @{ value = $resourceGroupName }
    serverName = @{ value = $serverName }
    location = @{ value = $location }
    administratorLoginPassword = @{ value = $password }
} }
$tempFile = New-TemporaryFile
try {
    # Restrict the short-lived plaintext parameter file to this Windows account.
    $acl = Get-Acl -LiteralPath $tempFile.FullName
    $acl.SetAccessRuleProtection($true, $false)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $tempFile.FullName -AclObject $acl
    $parameters | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tempFile.FullName -Encoding utf8
    $argument = '@' + $tempFile.FullName
    & az deployment sub create --name 'farmcraft-phase4-foundation-20261012' --location $location --template-file (Join-Path $PSScriptRoot 'phase4-sub.bicep') --parameters $argument --query properties.provisioningState --output tsv
    if ($LASTEXITCODE -ne 0) {
        throw 'Deployment failed. Inspect all partial resources and Azure-managed Container Apps groups; do not auto-clean.'
    }
} finally {
    $password = $null
    $passwordBytes = $null
    Remove-Item -LiteralPath $tempFile.FullName -Force -ErrorAction SilentlyContinue
}
