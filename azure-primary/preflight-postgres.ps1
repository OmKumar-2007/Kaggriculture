param(
    [string]$ResourceGroupName = 'rg-farmcraft-pgtest-20261011',
    [string]$ServerName = 'farmcraftpgtest20261011omk',
    [string]$Location = 'koreacentral',
    [string]$AllowedClientIp = '103.28.244.78'
)

$ErrorActionPreference = 'Stop'
if ($AllowedClientIp -eq '0.0.0.0' -or $AllowedClientIp -notmatch '^(?:\d{1,3}\.){3}\d{1,3}$') {
    throw 'Pass exactly one public IPv4 address, never 0.0.0.0.'
}
if ($ResourceGroupName -notmatch '^rg-farmcraft-pgtest-[a-z0-9-]+$' -or $ServerName -notmatch '^farmcraftpgtest[a-z0-9]{8,}$') {
    throw 'Use isolated test resource names.'
}
$template = Join-Path $PSScriptRoot 'postgres-eligibility-sub.bicep'
& az bicep build --file $template --stdout | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Bicep build failed.' }
$exists = (& az group exists --name $ResourceGroupName).Trim()
if ($LASTEXITCODE -ne 0 -or $exists -ne 'false') { throw 'The test resource group must not already exist.' }

# A random, disposable preview value is never printed or written to the repository.
$previewPassword = [Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(36)) + 'aA1!'
$parameters = @{ parameters = @{
    resourceGroupName = @{ value = $ResourceGroupName }
    serverName = @{ value = $ServerName }
    location = @{ value = $Location }
    allowedClientIp = @{ value = $AllowedClientIp }
    administratorLoginPassword = @{ value = $previewPassword }
} }
$tempFile = New-TemporaryFile
try {
    $parameters | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tempFile.FullName -Encoding utf8
    $argument = '@' + $tempFile.FullName
    & az deployment sub validate --name 'farmcraft-pgtest-preview' --location $Location --template-file $template --parameters $argument --output none
    if ($LASTEXITCODE -ne 0) { throw 'Subscription template validation failed.' }
    Write-Output 'ARM validation passed.'
    & az deployment sub what-if --name 'farmcraft-pgtest-preview' --location $Location --template-file $template --parameters $argument --result-format ResourceIdOnly --output json
    if ($LASTEXITCODE -ne 0) { throw 'Subscription what-if failed.' }
} finally {
    $previewPassword = $null
    Remove-Item -LiteralPath $tempFile.FullName -Force -ErrorAction SilentlyContinue
}
