param(
    [string]$ResourceGroupName = 'rg-farmcraft-azure-staging-20261012',
    [string]$ServerName = 'farmcraftstgpg20261012omk',
    [string]$Location = 'koreacentral'
)

$ErrorActionPreference = 'Stop'
$expectedSubscription = 'edcb16c2-9bcf-4533-8ca0-d182aaac9b70'
$subscription = (& az account show --query id --output tsv).Trim()
if ($LASTEXITCODE -ne 0 -or $subscription -ne $expectedSubscription) {
    throw 'Active Azure subscription is not the reviewed Azure for Students subscription.'
}
if ($ResourceGroupName -notmatch '^rg-farmcraft-azure-staging-[0-9]{8}$' -or $ServerName -notmatch '^farmcraftstgpg[0-9]{8}[a-z0-9]+$') {
    throw 'Use isolated staging names.'
}
if ((& az group exists --name $ResourceGroupName).Trim() -ne 'false') {
    throw 'The staging resource group already exists; do not preview over existing resources.'
}
$template = Join-Path $PSScriptRoot 'phase4-sub.bicep'
& az bicep build --file $template --stdout | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Bicep build failed.' }

# Preview secret is disposable. It is never an actual deployment credential.
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$previewBytes = New-Object byte[] 36
try { $random.GetBytes($previewBytes) } finally { $random.Dispose() }
$previewPassword = [Convert]::ToBase64String($previewBytes) + 'aA1!'
$parameters = @{ parameters = @{
    resourceGroupName = @{ value = $ResourceGroupName }
    serverName = @{ value = $ServerName }
    location = @{ value = $Location }
    administratorLoginPassword = @{ value = $previewPassword }
} }
$tempFile = New-TemporaryFile
try {
    $parameters | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $tempFile.FullName -Encoding utf8
    $argument = '@' + $tempFile.FullName
    & az deployment sub validate --name 'farmcraft-phase4-preview' --location $Location --template-file $template --parameters $argument --output none
    if ($LASTEXITCODE -ne 0) { throw 'ARM validation failed.' }
    Write-Output 'ARM validation passed; what-if follows. No resources are created.'
    & az deployment sub what-if --name 'farmcraft-phase4-preview' --location $Location --template-file $template --parameters $argument --result-format ResourceIdOnly --output json
    if ($LASTEXITCODE -ne 0) { throw 'ARM what-if failed.' }
} finally {
    $previewPassword = $null
    Remove-Item -LiteralPath $tempFile.FullName -Force -ErrorAction SilentlyContinue
}
