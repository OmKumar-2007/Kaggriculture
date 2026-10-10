param([switch]$AllowLogin)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'cli.ps1')
$accountText = & $AzCommand account show --output json 2>$null
if ($LASTEXITCODE -ne 0 -or -not $accountText) {
    if (-not $AllowLogin) { throw 'Azure CLI is not signed in. Run az login, then rerun First-Time Setup.' }
    & $AzCommand login
    if ($LASTEXITCODE -ne 0) { throw 'Azure login failed.' }
    $accountText = & $AzCommand account show --output json
}
$account = $accountText | ConvertFrom-Json
if ($account.state -ne 'Enabled') { throw 'Selected Azure subscription is not enabled.' }
Write-Host "Azure subscription: $($account.name) ($($account.state))"
if ($account.name -notmatch 'Student') { Write-Warning 'Subscription is not identified as Azure for Students. Review billing before provisioning.' }
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config = Join-Path $repo 'config\local-profiles\azure-site.json'
if (Test-Path -LiteralPath $config) {
    $site = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
    if ($site.region) {
        $location = & $AzCommand account list-locations --query "[?name=='$($site.region)'].name | [0]" --output tsv
        if ($LASTEXITCODE -ne 0 -or -not $location) { throw "Azure region '$($site.region)' is unavailable to this subscription." }
        Write-Host "Selected region: $location"
    }
}
foreach ($provider in @('Microsoft.App','Microsoft.Storage','Microsoft.Web','Microsoft.DBforPostgreSQL','Microsoft.Cache')) {
    $state = & $AzCommand provider show --namespace $provider --query registrationState --output tsv 2>$null
    Write-Host "$provider provider: $(if ($state) {$state} else {'UNKNOWN'})"
}
Write-Host 'Credit remaining and service quota: UNKNOWN until verified in Azure Cost Management and Quotas.'
Write-Host 'No Azure resources were created or changed.'
