param(
    [switch]$Approved,
    [string]$AllowedClientIp = '103.28.244.78'
)

# Do not run until the user approves the exact Phase 3 PostgreSQL test inventory.
$ErrorActionPreference = 'Stop'
if (-not $Approved) { throw 'Explicit Phase 3 provisioning approval is required.' }
if ($AllowedClientIp -eq '0.0.0.0' -or $AllowedClientIp -notmatch '^(?:\d{1,3}\.){3}\d{1,3}$') {
    throw 'Specify one public IPv4 address for the firewall.'
}
$currentIp = (Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 15).Trim()
if ($currentIp -ne $AllowedClientIp) { throw 'The test client public IP changed; review the firewall address before deployment.' }
$resourceGroupName = 'rg-farmcraft-pgtest-20261011'
$serverName = 'farmcraftpgtest20261011omk'
$location = 'koreacentral'
$exists = (& az group exists --name $resourceGroupName).Trim()
if ($LASTEXITCODE -ne 0 -or $exists -ne 'false') { throw 'The isolated test group already exists; inspect it before proceeding.' }

$credentialDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'config/local-profiles'
New-Item -ItemType Directory -Path $credentialDirectory -Force | Out-Null
$credentialPath = Join-Path $credentialDirectory 'pgtest-admin.dpapi'
if (Test-Path -LiteralPath $credentialPath) { throw 'A test credential archive already exists; inspect it before proceeding.' }
$password = [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(36)) + 'aA1!'
$password | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -LiteralPath $credentialPath
$parameters = @{ parameters = @{
    resourceGroupName = @{ value = $resourceGroupName }
    serverName = @{ value = $serverName }
    location = @{ value = $location }
    allowedClientIp = @{ value = $AllowedClientIp }
    administratorLoginPassword = @{ value = $password }
} }
$tempFile = New-TemporaryFile
try {
    $parameters | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tempFile.FullName -Encoding utf8
    $argument = '@' + $tempFile.FullName
    & az deployment sub create --name 'farmcraft-pgtest-create-20261011' --location $location --template-file (Join-Path $PSScriptRoot 'postgres-eligibility-sub.bicep') --parameters $argument --query properties.provisioningState -o tsv
    if ($LASTEXITCODE -ne 0) { throw 'Deployment failed. Inspect the isolated resource group for partial, billable resources.' }
} finally {
    $password = $null
    Remove-Item -LiteralPath $tempFile.FullName -Force -ErrorAction SilentlyContinue
}
